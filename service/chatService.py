from uuid import UUID, uuid4
import logging
import time
import asyncio
from collections.abc import AsyncIterator
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from configCredidential import get_settings
from repository.chatMessageRepository import ChatMessageRepository
from service.chatbotService import ChatbotService
from service.llmService import LLMService
from service.graphicService import GraphicService, GraphicResult
from service.sqlGuardRailsService import SQLWireguardService
from service.chatSessionService import ChatSessionService
from service.columnStatisticsService import ColumnStatisticsService
from template.promptTemplate import (
    build_nl_to_sql_prompt,
    build_analysis_prompt,
    build_graphic_generation_prompt,
)
from repository.chatQueryRepository import ChatQueryRepository
from schema.chatSchema import ChatResponse, PipelineStageInfo, GraphicItemResponse
from service.clarificationService import ClarificationService
from utils.dataClass.chatPipelineTypes import ChatPipelineContext
from utils.responses.chatResponseBuilder import (
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)
from utils.responses.sseHelpers import emit_sse_response, format_sse_metadata, format_sse_chunk, format_sse_done

settings = get_settings()
logger = logging.getLogger(__name__)




class ChatService:
    """Orchestrator pipeline RAG untuk chatbot KPI."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_service = ChatSessionService(db)
        self.query_repo = ChatQueryRepository(db)
        self.message_repo = ChatMessageRepository(db)
        self.chatbot_service = ChatbotService(db)
        self.clarification_service = ClarificationService(db)
        self.column_statistics_service = ColumnStatisticsService(db)
        self.llm_service = LLMService()
        self.wireguard_service = SQLWireguardService()
        self.graphic_service = GraphicService()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def verify_session(self, session_id: UUID, user_id: UUID) -> None:
        existing_session = await self.session_service.session_repo.get_by_id(session_id)
        if existing_session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sesi tidak lagi tersedia atau sudah dihapus oleh pengguna.",
            )
        if str(existing_session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke sesi ini.",
            )

    async def process_query_stream(
        self,
        user_message: str,
        user_id: UUID,
        user_role: str,
        session_id: UUID | None,
        show_sql: bool = False,
        context_from_clarification: Any = None,
    ) -> AsyncIterator[str]:
        """Streaming RAG pipeline orchestrator. Yields SSE events."""
        active_chatbot = await self.chatbot_service.get_active_chatbot_for_role(user_role)
        addon_prompt = getattr(active_chatbot, "addon_prompt", None)

        if session_id is not None:
            await self.verify_session(session_id, user_id)

        session_id = session_id or uuid4()
        await self.session_service.create_session_if_missing(
            session_id=session_id,
            user_id=user_id,
            first_message=user_message,
            chatbot_id=active_chatbot.id,
        )

        user_chat_message = None
        if context_from_clarification is None:
            user_chat_message = await self.session_service.create_user_message(
                session_id=session_id,
                message=user_message,
            )

        session_context = await self.clarification_service._build_recent_conversation_information(session_id, user_message)

        pipeline = self._build_pipeline_context(session_id, user_id, user_role, user_message)
        stages: list[PipelineStageInfo] = []
        total_start = time.monotonic()

        try:
            # Stage 1: Clarification
            if context_from_clarification is None:
                message_id = user_chat_message.message_id if user_chat_message else None
                clarification_result = await self._handle_clarification_stage(
                    stages=stages,
                    user_message=user_message,
                    user_role=user_role,
                    session_id=session_id,
                    addon_prompt=addon_prompt,
                    user_chat_message_id=message_id,
                    session_context=session_context
                )
                if clarification_result is not None:
                    async for event in clarification_result:
                        yield event
                    return
            else:
                stage = self._start_stage(stages, "Ambiguity Detection")
                self._complete_stage(stage, "completed", "Using disambiguated query")

            # Stage 2-3: NL-to-SQL + Visualization Decision (parallel)

            generated_sql, visualization_decision = await asyncio.gather(
                self._run_nl_to_sql_stage(stages, user_message, user_id, user_role, pipeline, addon_prompt, session_context),
                self._run_visualization_decision_stage(stages, user_message),
            )

            # Stage 4: SQL Validation
            validation = self._run_sql_validation_stage(stages, generated_sql, user_id, user_role, pipeline)
            if not validation.is_valid:
                resp = build_security_blocked_response(session_id, stages)
                async for event in emit_sse_response(session_id, stages, resp.message):
                    yield event
                return

            sanitized_sql = validation.sanitized_sql or ""
            logger.error("Sanitized SQL: %s", sanitized_sql)

            # Stage 5: SQL Execution
            query_result, rows_count = await self._run_sql_execution_stage(stages, sanitized_sql, pipeline)

            # Stage 6: Graphic Generation (conditional)
            graphic_results: list[GraphicResult] = []
            unsupported_message = None
            if visualization_decision.is_visualize:
                req_type = (visualization_decision.chart_type or "").strip().lower()
                supported_types = {"bar", "batang", "donut", "donat", "line", "garis"}
                if req_type not in supported_types:
                    unsupported_message = f"⚠️ **Maaf, tipe grafik '{visualization_decision.chart_type}' tidak didukung oleh sistem.** Sistem saat ini hanya mendukung grafik **Batang**, **Donat**, dan **Garis**.\n\nBerikut adalah data dalam bentuk teks:\n\n"
                    visualization_decision.is_visualize = False

            if visualization_decision.is_visualize:
                graphic_results = self._run_graphic_production_stage(
                    stages, query_result, visualization_decision.chart_type or "bar", session_id,
                )

            # Stage 7: Streaming Narrative Analysis
            async for event in self._stream_narrative_analysis(
                stages=stages,
                session_id=session_id,
                user_message=user_message,
                sanitized_sql=sanitized_sql,
                query_result=query_result,
                rows_count=rows_count,
                graphic_results=graphic_results,
                addon_prompt=addon_prompt,
                show_sql=show_sql,
                total_start=total_start,
                unsupported_message=unsupported_message,
            ):
                yield event

        except Exception as error:
            await self.db.rollback()
            raise await self._handle_pipeline_error(pipeline, error)

    # ------------------------------------------------------------------
    # Extracted pipeline sub-flows
    # ------------------------------------------------------------------

    async def _handle_clarification_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
        user_role: str,
        session_id: UUID,
        addon_prompt: str | None,
        user_chat_message_id: UUID | str | None,
        session_context: str | None
    ) -> AsyncIterator[str] | None:
        """Handle ambiguity detection stage.

        Returns:
            AsyncIterator[str] if clarification questions should be sent to user
                (caller must yield from it and return).
            None if no clarification needed — pipeline should continue.
        """
        stage = self._start_stage(stages, "Ambiguity Detection")

        clarification_response = await self.clarification_service.process_user_query(
            user_query=user_message,
            user_role=user_role,
            session_id=session_id,
            addon_prompt=addon_prompt,
            message_id=self._coerce_message_id(user_chat_message_id) if user_chat_message_id else None,
            session_context=session_context
        )

        if clarification_response is None:
            self._complete_stage(stage, "completed", "No clarification needed")
            return None

        if clarification_response.clarifying_question:
            self._complete_stage(stage, "completed", "Clarification question generated")
            query_message = build_clarification_prompt_message(
                user_message=user_message,
                questions=[q.question for q in (clarification_response.questions or [])],
            )
            await self.session_service.create_chatbot_message(
                session_id=session_id,
                message=query_message,
            )
            await self.db.commit()
            return emit_sse_response(
                session_id=session_id,
                stages=stages,
                message=query_message,
                clarification_questions=clarification_response.questions,
            )

        self._complete_stage(stage, "completed", "No clarification needed")
        return None

    async def _stream_narrative_analysis(
        self,
        stages: list[PipelineStageInfo],
        session_id: UUID,
        user_message: str,
        sanitized_sql: str,
        query_result: list[dict],
        rows_count: int,
        graphic_results: list[GraphicResult],
        addon_prompt: str | None,
        show_sql: bool,
        total_start: float,
        unsupported_message: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream narrative analysis: metadata → LLM tokens → done, then persist."""
        analysis_stage = self._start_stage(stages, "result_analysis")
        analysis_prompt = build_analysis_prompt(
            user_query=user_message,
            executed_sql=sanitized_sql,
            query_result=query_result,
            rows_count=rows_count,
            addon_prompt=addon_prompt,
        )

        total_ms = int((time.monotonic() - total_start) * 1000)
        graphics_payload = build_graphics_payload(graphic_results)

        metadata_resp = ChatResponse(
            session_id=session_id,
            message="",
            generated_sql=sanitized_sql if show_sql else None,
            graphics=[
                GraphicItemResponse(
                    kpi_name=r.kpi_name or None,
                    chart_type=r.chart_type,
                    image_url=r.image_url,
                )
                for r in graphic_results
            ],
            rows_returned=rows_count,
            execution_time_ms=total_ms,
            pipeline_stages=stages,
            query_result=query_result,
        )
        payload = metadata_resp.model_dump(mode="json")
        metadata = {k: v for k, v in payload.items() if k != "message"}
        yield format_sse_metadata(metadata)

        full_narrative = unsupported_message or ""
        if unsupported_message:
            yield format_sse_chunk(unsupported_message)

        if rows_count == 0 or not query_result:
            fallback = (unsupported_message or "") + "Mohon maaf, tidak ada data valid untuk pertanyaan anda atau pertanyaan anda diluar konteks domain sistem ini."
            self._complete_stage(analysis_stage, "success", "Tidak ada data ditemukan.")
            yield format_sse_chunk(fallback)
            yield format_sse_done()
            await self.session_service.create_chatbot_message(
                session_id=session_id,
                message=fallback,
                graphics=graphics_payload,
            )
            await self.db.commit()
            return

        try:
            async for token in self.llm_service.analyze_result_stream(analysis_prompt):
                full_narrative += token
                yield format_sse_chunk(token)
                await asyncio.sleep(0)
            self._complete_stage(analysis_stage, "success", "Analisis naratif berhasil dibuat.")
        except HTTPException as e:
            if e.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                self._complete_stage(analysis_stage, "degraded", "Dilewati karena rate limit.")
                fallback = (
                    "Data berhasil diambil, namun analisis AI belum tersedia "
                    "karena kuota/rate limit LLM tercapai. Silakan coba lagi nanti."
                )
                yield format_sse_chunk(fallback)
                full_narrative = fallback
            else:
                raise

        yield format_sse_done()

        await self.session_service.create_chatbot_message(
            session_id=session_id,
            message=full_narrative,
            graphics=graphics_payload,
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_pipeline_context(
        session_id: UUID,
        user_id: UUID,
        user_role: str,
        user_message: str,
    ) -> ChatPipelineContext:
        return ChatPipelineContext(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            user_query=user_message,
        )

    @staticmethod
    def _coerce_message_id(message_id: UUID | str) -> UUID:
        return message_id if isinstance(message_id, UUID) else UUID(str(message_id))

    @staticmethod
    def _start_stage(stages: list[PipelineStageInfo], stage_name: str) -> PipelineStageInfo:
        stage = PipelineStageInfo(stage=stage_name, status="running")
        stages.append(stage)
        return stage

    @staticmethod
    def _complete_stage(stage: PipelineStageInfo, status_value: str, detail: str) -> None:
        stage.status = status_value
        stage.detail = detail

    @staticmethod
    async def _handle_pipeline_error(
        pipeline: ChatPipelineContext,
        error: Exception,
    ) -> HTTPException:
        pipeline.execution_status = "error"

        if isinstance(error, HTTPException):
            if error.status_code in (
                status.HTTP_408_REQUEST_TIMEOUT,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                status.HTTP_429_TOO_MANY_REQUESTS,
            ):
                return error

            if error.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                logger.error("Error server saat memproses query: %s", error)
                return HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan chatbot sementara tidak tersedia. Silakan coba lagi.",
                )

            return HTTPException(
                status_code=error.status_code,
                detail="Permintaan tidak dapat diproses.",
            )

        logger.error("Error tidak terduga dalam memproses query: %s", error)
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan saat memproses permintaan Anda. Silakan coba lagi.",
        )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    async def _run_nl_to_sql_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
        addon_prompt: str | None = None,
        session_context: str | None = None,
    ) -> str:
        stage = self._start_stage(stages, "nl_to_sql")
        try:
            column_statistics = await self.column_statistics_service.build_nl_to_sql_statistics()
            nl_prompt = build_nl_to_sql_prompt(
                user_query=user_message,
                user_id=user_id,
                user_role=user_role,
                addon_prompt=addon_prompt,
                column_statistics=column_statistics,
                session_context=session_context
            )
            generated_sql = await self.llm_service.generate_sql(nl_prompt)
            pipeline.generated_sql = generated_sql
            self._complete_stage(stage, "success", "SQL berhasil digenerate.")
            return generated_sql
        except HTTPException as error:
            if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                self._complete_stage(
                    stage,
                    "degraded",
                    "SQL tidak dapat digenerate karena layanan AI sedang tidak tersedia.",
                )
            else:
                self._complete_stage(stage, "failed", "Gagal melakukan proses NL-to-SQL.")
            raise

    async def _run_visualization_decision_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
    ):
        stage = self._start_stage(stages, "visualization_decision")
        prompt = build_graphic_generation_prompt(user_query=user_message)
        decision = await self.llm_service.decide_visualization_request(prompt=prompt)
        if decision.is_visualize:
            detail = f"Permintaan visualisasi terdeteksi (chart: {decision.chart_type or 'bar'})."
        else:
            detail = "Permintaan visualisasi tidak terdeteksi."
        self._complete_stage(stage, "success", detail)
        return decision

    def _run_sql_validation_stage(
        self,
        stages: list[PipelineStageInfo],
        generated_sql: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
    ):
        stage = self._start_stage(stages, "sql_validation")
        validation = self.wireguard_service.validate(
            sql=generated_sql,
            user_id=user_id,
            user_role=user_role,
        )
        pipeline.wireguard_status = "PASS" if validation.is_valid else "FAIL"
        pipeline.wireguard_reason = validation.reason

        if validation.is_valid:
            self._complete_stage(stage, "success", "Query lolos validasi keamanan.")
        else:
            self._complete_stage(stage, "blocked", validation.reason or "")
        return validation

    async def _run_sql_execution_stage(
        self,
        stages: list[PipelineStageInfo],
        sanitized_sql: str,
        pipeline: ChatPipelineContext,
    ) -> tuple[list[dict], int]:
        stage = self._start_stage(stages, "sql_execution")
        exec_start = time.monotonic()

        logger.info("Menjalankan SQL: %s", sanitized_sql)

        try:
            query_result, rows_count = await asyncio.wait_for(
                self.query_repo.execute_read_query(sanitized_sql),
                timeout=settings.SQL_EXECUTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Eksekusi query melebihi batas waktu {settings.SQL_EXECUTION_TIMEOUT} detik.",
            )
        except Exception as e:
            logger.error("Error saat mengeksekusi SQL: %s", e)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Query tidak dapat dieksekusi. Silakan coba pertanyaan yang berbeda.",
            ) from e

        exec_ms = int((time.monotonic() - exec_start) * 1000)
        pipeline.execution_status = "success"
        pipeline.rows_returned = rows_count
        pipeline.execution_time_ms = exec_ms
        self._complete_stage(
            stage,
            "success",
            f"{rows_count} baris data ditemukan ({exec_ms}ms).",
        )
        return query_result, rows_count

    def _run_graphic_production_stage(
        self,
        stages: list[PipelineStageInfo],
        query_result: list[dict],
        chart_type: str,
        session_id: UUID,
    ) -> list[GraphicResult]:
        stage = self._start_stage(stages, "graphic_generation")
        try:
            results = self.graphic_service.generateGraphicPerKpi(
                query_result=query_result,
                chart_type=chart_type,
                session_id=session_id,
            )
            chart_types = list(dict.fromkeys(r.chart_type for r in results))
            self._complete_stage(
                stage,
                "success",
                f"{len(results)} grafik berhasil digenerate (type: {', '.join(chart_types)}).",
            )
            return results
        except ValueError as error:
            self._complete_stage(stage, "degraded", str(error))
            return []


