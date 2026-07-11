from uuid import UUID, uuid4
import logging
import time
import asyncio
from collections.abc import AsyncIterator
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from utils.responses.chatResponseBuilder import (
    _build_metadata_event,
    _handle_no_data,
    _handle_unsupported_visualization_type
)
from configCredidential import get_settings
from repository.chatMessageRepository import ChatMessageRepository
from service.chatbotService import ChatbotService
from service.llmService import LLMService
from service.graphicService import GraphicService, GraphicResult
from service.sqlGuardRailsService import SQLGuardrailsService
from service.chatSessionService import ChatSessionService
from service.columnStatisticsService import ColumnStatisticsService
from template.promptTemplate import (
    build_nl_to_sql_prompt,
    build_analysis_prompt,
    build_graphic_generation_prompt,
)
from repository.chatQueryRepository import ChatQueryRepository
from schema.chatSchema import PipelineStageInfo
from service.clarificationService import ClarificationService
from utils.dataClass.chatPipelineTypes import ChatPipelineContext
from utils.responses.chatResponseBuilder import (
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)
from utils.helper.sseHelpers import emit_sse_response, format_sse_chunk, format_sse_done
from utils.helper.pipelineStageHelpers import (
    build_pipeline_context,
    coerce_message_id,
    complete_stage,
    map_pipeline_error,
    start_stage,
)

settings = get_settings()
logger = logging.getLogger(__name__)


class ChatService:
    """Orchestrator pipeline RAG untuk chatbot KPI."""

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.session_service: ChatSessionService = ChatSessionService(db)
        self.query_repo: ChatQueryRepository = ChatQueryRepository(db)
        self.message_repo: ChatMessageRepository = ChatMessageRepository(db)
        self.chatbot_service: ChatbotService = ChatbotService(db)
        self.clarification_service: ClarificationService = ClarificationService(db)
        self.column_statistics_service: ColumnStatisticsService = ColumnStatisticsService(db)
        self.llm_service: LLMService = LLMService()
        self.guardrails_service: SQLGuardrailsService = SQLGuardrailsService()
        self.graphic_service: GraphicService = GraphicService()

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
            user_chat_message = await self.create_user_message(
                session_id=session_id,
                message=user_message,
            )

        session_context = await self.clarification_service._build_recent_conversation_information(session_id, user_message)

        pipeline = build_pipeline_context(session_id, user_id, user_role, user_message)
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
                stage = start_stage(stages, "Ambiguity Detection")
                complete_stage(stage, "completed", "Using disambiguated query")

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
            unsupported_message = _handle_unsupported_visualization_type(visualization_decision)

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
            raise map_pipeline_error(pipeline, error)

    async def create_user_message(self, session_id: UUID, message: str):
        return await self.message_repo.create(
            session_id=session_id,
            message=message,
            is_sender_chatbot=False,
        )

    async def create_chatbot_message(
        self,
        session_id: UUID,
        message: str,
        graphics: list[dict] | None = None,
    ):
        chat_message = await self.message_repo.create(
            session_id=session_id,
            message=message,
            is_sender_chatbot=True,
        )
        if graphics:
            await self.message_repo.create_graphics(
                message_id=chat_message.message_id,
                graphics=graphics,
            )
        return chat_message

    async def _persist_chatbot_message(
            self,
            session_id: UUID,
            message: str,
            graphic_results: list[GraphicResult],
    ) -> None:
        graphics_payload = build_graphics_payload(graphic_results)
        await self.create_chatbot_message(
            session_id=session_id,
            message=message,
            graphics=graphics_payload,
        )
        await self.db.commit()

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

    # ------------------------------------------------------------------
    # Pipeline stages
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

        stage = start_stage(stages, "Ambiguity Detection")

        clarification_response = await self.clarification_service.process_user_query(
            user_query=user_message,
            user_role=user_role,
            session_id=session_id,
            addon_prompt=addon_prompt,
            message_id=coerce_message_id(user_chat_message_id) if user_chat_message_id else None,
            session_context=session_context
        )

        if clarification_response is None:
            complete_stage(stage, "completed", "No clarification needed")
            return None

        if clarification_response.is_out_of_scope:
            complete_stage(stage, "completed", "Query blocked by scope or policy")
            query_message = clarification_response.message or "Mohon maaf pertanyaan anda diluar konteks domain sistem atau melanggar aturan yang telah ditetapkan"
            await self.create_chatbot_message(
                session_id=session_id,
                message=query_message,
            )
            await self.db.commit()
            return emit_sse_response(
                session_id=session_id,
                stages=stages,
                message=query_message,
            )

        if clarification_response.clarifying_question:
            complete_stage(stage, "completed", "Clarification question generated")
            query_message = build_clarification_prompt_message(
                user_message=user_message,
                questions=[q.question for q in (clarification_response.questions or [])],
            )
            await self.create_chatbot_message(
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

        complete_stage(stage, "completed", "No clarification needed")
        return None

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
        stage = start_stage(stages, "nl_to_sql")
        try:
            column_statistics = await self.column_statistics_service.get_statistics_text()
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
            complete_stage(stage, "success", "SQL berhasil digenerate.")
            return generated_sql
        except HTTPException as error:
            if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                complete_stage(
                    stage,
                    "degraded",
                    "SQL tidak dapat digenerate karena layanan AI sedang tidak tersedia.",
                )
            else:
                complete_stage(stage, "failed", "Gagal melakukan proses NL-to-SQL.")
            raise

    async def _run_visualization_decision_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
    ):
        stage = start_stage(stages, "visualization_decision")
        prompt = build_graphic_generation_prompt(user_query=user_message)
        decision = await self.llm_service.decide_visualization_request(prompt=prompt)
        if decision.is_visualize:
            detail = f"Permintaan visualisasi terdeteksi (chart: {decision.chart_type or 'bar'})."
        else:
            detail = "Permintaan visualisasi tidak terdeteksi."
        complete_stage(stage, "success", detail)
        return decision

    def _run_sql_validation_stage(
        self,
        stages: list[PipelineStageInfo],
        generated_sql: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
    ):
        stage = start_stage(stages, "sql_validation")
        validation = self.guardrails_service.validate(
            sql=generated_sql,
            user_id=user_id,
            user_role=user_role,
        )
        pipeline.wireguard_status = "PASS" if validation.is_valid else "FAIL"
        pipeline.wireguard_reason = validation.reason

        if validation.is_valid:
            complete_stage(stage, "success", "Query lolos validasi keamanan.")
        else:
            complete_stage(stage, "blocked", validation.reason or "")
        return validation

    async def _run_sql_execution_stage(
        self,
        stages: list[PipelineStageInfo],
        sanitized_sql: str,
        pipeline: ChatPipelineContext,
    ) -> tuple[list[dict], int]:
        stage = start_stage(stages, "sql_execution")
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
        complete_stage(
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
        stage = start_stage(stages, "graphic_generation")
        try:
            results = self.graphic_service.generateGraphicPerKpi(
                query_result=query_result,
                chart_type=chart_type,
                session_id=session_id,
            )
            chart_types = list(dict.fromkeys(r.chart_type for r in results))
            complete_stage(
                stage,
                "success",
                f"{len(results)} grafik berhasil digenerate (type: {', '.join(chart_types)}).",
            )
            return results
        except ValueError as error:
            complete_stage(stage, "degraded", str(error))
            return []

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
        analysis_stage = start_stage(stages, "result_analysis")
        total_ms = int((time.monotonic() - total_start) * 1000)

        yield _build_metadata_event(
            session_id, sanitized_sql, graphic_results, rows_count, total_ms, stages, query_result, show_sql
        )

        prefix = unsupported_message or ""
        if unsupported_message:
            yield format_sse_chunk(unsupported_message)

        has_data = rows_count > 0 and bool(query_result)
        if not has_data:
            full_narrative = await _handle_no_data(analysis_stage, prefix)
            await self._persist_chatbot_message(session_id, full_narrative, graphic_results)
            yield format_sse_chunk(full_narrative)
            yield format_sse_done()
            return

        narrative_out: list[str] = []
        async for event in self._stream_llm_analysis(
            analysis_stage, narrative_out, user_message, sanitized_sql,
            query_result, rows_count, addon_prompt, prefix,
        ):
            yield event

        full_narrative = narrative_out[0] if narrative_out else prefix
        yield format_sse_done()
        await self._persist_chatbot_message(session_id, full_narrative, graphic_results)

    async def _stream_llm_analysis(
            self,
            analysis_stage,
            narrative_out: list[str],
            user_message: str,
            sanitized_sql: str,
            query_result: list[dict],
            rows_count: int,
            addon_prompt: str | None,
            prefix: str,
    ) -> AsyncIterator[str]:
        """Yield SSE token chunks; append the full narrative to narrative_out for the caller."""
        analysis_prompt = build_analysis_prompt(
            user_query=user_message,
            executed_sql=sanitized_sql,
            query_result=query_result,
            rows_count=rows_count,
            addon_prompt=addon_prompt,
        )

        accumulated = ""
        try:
            async for token in self.llm_service.analyze_result_stream(analysis_prompt):
                accumulated += token
                yield format_sse_chunk(token)
                await asyncio.sleep(0)
            complete_stage(analysis_stage, "success", "Analisis naratif berhasil dibuat.")
        except HTTPException as e:
            if e.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
                raise
            complete_stage(analysis_stage, "degraded", "Dilewati karena rate limit.")
            accumulated = (
                "Data berhasil diambil, namun analisis AI belum tersedia "
                "karena kuota/rate limit LLM tercapai. Silakan coba lagi nanti."
            )
            yield format_sse_chunk(accumulated)

        narrative_out.append(prefix + accumulated)

