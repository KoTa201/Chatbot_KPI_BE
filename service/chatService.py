from uuid import UUID
import json
import logging
import time
import uuid
import asyncio
from collections.abc import AsyncIterator
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from configCredidential import get_settings
from service.chatbotService import ChatbotService
from service.llmService import LLMService, VisualizationDecision
from service.graphicService import GraphicSeervice, GraphicResult
from service.sqlGuardRailsService import SQLWireguardService
from service.chatSessionService import ChatSessionService
from service.columnStatisticsService import ColumnStatisticsService
from template.promptTemplate import build_nl_to_sql_prompt, build_analysis_prompt, build_graphic_generation_prompt
from repository.clarificationRepository import ClarificationRepository
from repository.chatQueryRepository import ChatQueryRepository
from schema.chatSchema import ChatResponse, PipelineStageInfo, GraphicItemResponse
from service.clarificationService import ClarificationService
from utils.dataClass.chatPipelineTypes import ChatPipelineContext
from utils.responses.chatResponseBuilder import (
    build_ai_unavailable_response,
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)
from utils.sessionContextManager import SessionContextManager

settings = get_settings()
logger = logging.getLogger(__name__)

llm = LLMService()
wireguard = SQLWireguardService()
graphic_service = GraphicSeervice()


class ChatService:
    """Orchestrator pipeline RAG untuk chatbot KPI."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_service = ChatSessionService(db)
        self.clarification_repo = ClarificationRepository(db)
        self.query_repo = ChatQueryRepository(db)
        self.chatbot_service = ChatbotService(db)
        self.clarification_service = ClarificationService(db)
        self.column_statistics_service = ColumnStatisticsService(db)

    async def process_query(
        self,
        user_message: str,
        user_id: UUID,
        user_role: str,
        session_id: UUID | None,
        show_sql: bool = False,
        context_from_clarification: Any = None,
    ) -> ChatResponse:

        active_chatbot = await self.chatbot_service.get_active_chatbot_for_role(user_role)
        addon_prompt = getattr(active_chatbot, "addon_prompt", None)

        session_id = session_id or uuid.uuid4()
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
        pipeline = self._build_pipeline_context(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            user_message=user_message,
        )
        stages: list[PipelineStageInfo] = []
        total_start = time.monotonic()

        try:
            clarification_stage = self._start_stage(
                stages, "Ambiguity Detection")
            if context_from_clarification is None:
                clarification_response = await self.clarification_service.process_user_query(
                    user_query=user_message,
                    user_role=user_role,
                    session_id=session_id,
                    addon_prompt=addon_prompt,
                    message_id=self._coerce_message_id(user_chat_message.message_id) if user_chat_message is not None else None,
                )

                if clarification_response is not None:
                    self._complete_stage(
                        clarification_stage, "completed", "Clarification question generated")

                    query_message = build_clarification_prompt_message(
                        user_message=user_message,
                        questions=[q.question for q in clarification_response.questions],
                    )
                    await self.session_service.create_chatbot_message(
                        session_id=session_id,
                        message=query_message,
                    )
                    await self.db.commit()
                    return ChatResponse(
                        session_id=session_id,
                        message=query_message,
                        clarification_questions=clarification_response.questions,
                        pipeline_stages=stages,
                    )
                else:
                    self._complete_stage(
                        clarification_stage, "completed", "No clarification needed")
            else:
                self._complete_stage(clarification_stage,
                                     "completed", "Using disambiguated query")
                SessionContextManager.get_session_context(session_id)
            try:
                generated_sql = await self._run_nl_to_sql_stage(
                    stages=stages,
                    user_message=user_message,
                    user_id=user_id,
                    user_role=user_role,
                    pipeline=pipeline,
                    addon_prompt=addon_prompt,
                )
                visualization_decision = await self._run_visualization_decision_stage(
                    stages=stages,
                    user_message=user_message,
                )
            except HTTPException as error:
                if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    pipeline.execution_status = "degraded"
                    return build_ai_unavailable_response(session_id, stages)
                raise
            validation = self._run_sql_validation_stage(
                stages=stages,
                generated_sql=generated_sql,
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )
            if not validation.is_valid:
                return build_security_blocked_response(session_id, stages)

            sanitized_sql = validation.sanitized_sql
            query_result, rows_count = await self._run_sql_execution_stage(
                stages=stages,
                sanitized_sql=sanitized_sql or "",
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )
            graphic_results: list[GraphicResult] = []
            if visualization_decision.is_visualize:
                graphic_results = self._run_graphic_generation_stage(
                    stages=stages,
                    query_result=query_result,
                    chart_type=visualization_decision.chart_type or "bar",
                    session_id=session_id,
                )
            narrative = await self._run_result_analysis_stage(
                stages=stages,
                user_query=user_message,
                executed_sql=sanitized_sql or "",
                query_result=query_result,
                rows_count=rows_count,
                addon_prompt=addon_prompt,
            )

            total_ms = int((time.monotonic() - total_start) * 1000)
            graphics_payload = build_graphics_payload(graphic_results)
            await self.session_service.create_chatbot_message(
                session_id=session_id,
                message=narrative,
                graphics=graphics_payload,
            )
            await self.db.commit()

            return ChatResponse(
                session_id=session_id,
                message=narrative,
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
            )

        except Exception as error:
            await self.db.rollback()
            raise await self._handle_pipeline_error(pipeline, error)

    async def process_query_stream(
        self,
        user_message: str,
        user_id: UUID,
        user_role: str,
        session_id: UUID | None,
        show_sql: bool = False,
        context_from_clarification: Any = None,
    ) -> AsyncIterator[str]:
        """
        Streaming version of process_query.
        Yields SSE events (metadata first, then LLM token chunks, then done).
        """
        active_chatbot = await self.chatbot_service.get_active_chatbot_for_role(user_role)
        addon_prompt = getattr(active_chatbot, "addon_prompt", None)

        session_id = session_id or uuid.uuid4()
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
        pipeline = self._build_pipeline_context(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            user_message=user_message,
        )
        stages: list[PipelineStageInfo] = []
        total_start = time.monotonic()

        try:
            clarification_stage = self._start_stage(stages, "Ambiguity Detection")
            if context_from_clarification is None:
                clarification_response = await self.clarification_service.process_user_query(
                    user_query=user_message,
                    user_role=user_role,
                    session_id=session_id,
                    addon_prompt=addon_prompt,
                    message_id=self._coerce_message_id(user_chat_message.message_id) if user_chat_message is not None else None,
                )

                if clarification_response is not None:
                    self._complete_stage(clarification_stage, "completed", "Clarification question generated")
                    query_message = build_clarification_prompt_message(
                        user_message=user_message,
                        questions=[q.question for q in clarification_response.questions],
                    )
                    await self.session_service.create_chatbot_message(
                        session_id=session_id,
                        message=query_message,
                    )
                    await self.db.commit()
                    # Yield the clarification response as a non-streamed metadata+message
                    clarify_resp = ChatResponse(
                        session_id=session_id,
                        message=query_message,
                        clarification_questions=clarification_response.questions,
                        pipeline_stages=stages,
                    )
                    payload = clarify_resp.model_dump(mode="json")
                    metadata = {k: v for k, v in payload.items() if k != "message"}
                    message = payload.get("message") or ""
                    yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
                    for word in self._message_chunks(message):
                        yield f"event: message\ndata: {json.dumps({'chunk': word}, ensure_ascii=False)}\n\n"
                    yield "event: done\ndata: {}\n\n"
                    return
                else:
                    self._complete_stage(clarification_stage, "completed", "No clarification needed")
            else:
                self._complete_stage(clarification_stage, "completed", "Using disambiguated query")
                SessionContextManager.get_session_context(session_id)

            try:
                generated_sql = await self._run_nl_to_sql_stage(
                    stages=stages,
                    user_message=user_message,
                    user_id=user_id,
                    user_role=user_role,
                    pipeline=pipeline,
                    addon_prompt=addon_prompt,
                )
                visualization_decision = await self._run_visualization_decision_stage(
                    stages=stages,
                    user_message=user_message,
                )
            except HTTPException as error:
                if error.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
                    pipeline.execution_status = "degraded"
                    resp = build_ai_unavailable_response(session_id, stages)
                    payload = resp.model_dump(mode="json")
                    metadata = {k: v for k, v in payload.items() if k != "message"}
                    message = payload.get("message") or ""
                    yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
                    for word in self._message_chunks(message):
                        yield f"event: message\ndata: {json.dumps({'chunk': word}, ensure_ascii=False)}\n\n"
                    yield "event: done\ndata: {}\n\n"
                    return
                raise

            validation = self._run_sql_validation_stage(
                stages=stages,
                generated_sql=generated_sql,
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )
            if not validation.is_valid:
                resp = build_security_blocked_response(session_id, stages)
                payload = resp.model_dump(mode="json")
                metadata = {k: v for k, v in payload.items() if k != "message"}
                message = payload.get("message") or ""
                yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"
                for word in self._message_chunks(message):
                    yield f"event: message\ndata: {json.dumps({'chunk': word}, ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return

            sanitized_sql = validation.sanitized_sql
            query_result, rows_count = await self._run_sql_execution_stage(
                stages=stages,
                sanitized_sql=sanitized_sql or "",
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )
            graphic_results: list[GraphicResult] = []
            if visualization_decision.is_visualize:
                graphic_results = self._run_graphic_generation_stage(
                    stages=stages,
                    query_result=query_result,
                    chart_type=visualization_decision.chart_type or "bar",
                    session_id=session_id,
                )

            # --- Begin streaming narrative ---
            analysis_stage = self._start_stage(stages, "result_analysis")
            analysis_prompt = build_analysis_prompt(
                user_query=user_message,
                executed_sql=sanitized_sql or "",
                query_result=query_result,
                rows_count=rows_count,
                addon_prompt=addon_prompt,
            )

            total_ms = int((time.monotonic() - total_start) * 1000)
            graphics_payload = build_graphics_payload(graphic_results)

            # Build metadata payload (without the narrative message — not known yet)
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
            )
            payload = metadata_resp.model_dump(mode="json")
            metadata = {k: v for k, v in payload.items() if k != "message"}
            yield f"event: metadata\ndata: {json.dumps(metadata, ensure_ascii=False)}\n\n"

            # Stream LLM tokens
            full_narrative = ""
            try:
                async for token in llm.analyze_result_stream(analysis_prompt):
                    full_narrative += token
                    yield f"event: message\ndata: {json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
                    # Yield control to the event loop so each chunk is flushed
                    # to the TCP buffer immediately (prevents batch buffering).
                    await asyncio.sleep(0)
                self._complete_stage(analysis_stage, "success", "Analisis naratif berhasil dibuat.")
            except HTTPException as e:
                if e.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    self._complete_stage(analysis_stage, "degraded", "Dilewati karena rate limit.")
                    fallback = (
                        "Data berhasil diambil, namun analisis AI belum tersedia "
                        "karena kuota/rate limit LLM tercapai. Silakan coba lagi nanti."
                    )
                    yield f"event: message\ndata: {json.dumps({'chunk': fallback}, ensure_ascii=False)}\n\n"
                    full_narrative = fallback
                else:
                    raise

            yield "event: done\ndata: {}\n\n"

            # Persist the completed narrative
            await self.session_service.create_chatbot_message(
                session_id=session_id,
                message=full_narrative,
                graphics=graphics_payload,
            )
            await self.db.commit()

        except Exception as error:
            await self.db.rollback()
            raise await self._handle_pipeline_error(pipeline, error)

    @staticmethod
    def _message_chunks(message: str) -> list[str]:
        if not message:
            return []
        words = message.split(" ")
        if len(words) == 1:
            return words
        chunks: list[str] = []
        last_index = len(words) - 1
        for index, word in enumerate(words):
            chunks.append(f"{word} " if index < last_index else word)
        return chunks



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
                logger.error(f"Error server saat memproses query: {error}")
                return HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan chatbot sementara tidak tersedia. Silakan coba lagi.",
                )

            return HTTPException(
                status_code=error.status_code,
                detail="Permintaan tidak dapat diproses.",
            )

        logger.error(f"Error tidak terduga dalam memproses query: {error}")
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan saat memproses permintaan Anda. Silakan coba lagi.",
        )

    async def _run_nl_to_sql_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
        addon_prompt: str | None = None,
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
            )
            generated_sql = await llm.generate_sql(nl_prompt)
            logger.debug("SQL generated for chat pipeline")
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
                self._complete_stage(
                    stage, "failed", "Gagal melakukan proses NL-to-SQL.")
            raise

    async def _run_visualization_decision_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
    ) -> VisualizationDecision:
        stage = self._start_stage(stages, "visualization_decision")
        n2_prompt = build_graphic_generation_prompt(user_query=user_message)
        visualization_decision = await llm.decide_visualization_request(prompt=n2_prompt)
        if visualization_decision.is_visualize:
            detail = (
                "Permintaan visualisasi terdeteksi "
                f"(chart: {visualization_decision.chart_type or 'bar'})."
            )
        else:
            detail = "Permintaan visualisasi tidak terdeteksi."
        self._complete_stage(stage, "success", detail)
        return visualization_decision

    def _run_sql_validation_stage(
        self,
        stages: list[PipelineStageInfo],
        generated_sql: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
    ):
        stage = self._start_stage(stages, "sql_validation")
        validation = wireguard.validate(
            sql=generated_sql,
            user_id=user_id,
            user_role=user_role,
        )
        pipeline.wireguard_status = "PASS" if validation.is_valid else "FAIL"
        pipeline.wireguard_reason = validation.reason

        if validation.is_valid:
            self._complete_stage(
                stage, "success", "Query lolos validasi keamanan.")
        else:
            self._complete_stage(stage, "blocked", validation.reason or "")
        return validation

    async def _run_sql_execution_stage(
        self,
        stages: list[PipelineStageInfo],
        sanitized_sql: str,
        user_id: UUID,
        user_role: str,
        pipeline: ChatPipelineContext,
    ) -> tuple[list[dict], int]:
        stage = self._start_stage(stages, "sql_execution")
        exec_start = time.monotonic()

        logger.info(
            f"Menjalankan SQL untuk user_id={user_id} role={user_role}: {sanitized_sql}"
        )

        query_result, rows_count = await self._execute_sql(sanitized_sql)
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

    async def _run_result_analysis_stage(
        self,
        stages: list[PipelineStageInfo],
        user_query: str,
        executed_sql: str,
        query_result: list[dict],
        rows_count: int,
        addon_prompt: str | None = None,
    ) -> str:
        stage = self._start_stage(stages, "result_analysis")
        analysis_prompt = build_analysis_prompt(
            user_query=user_query,
            executed_sql=executed_sql,
            query_result=query_result,
            rows_count=rows_count,
            addon_prompt=addon_prompt,
        )
        try:
            narrative = await llm.analyze_result(analysis_prompt)
            self._complete_stage(
                stage, "success", "Analisis naratif berhasil dibuat.")
            return narrative
        except HTTPException as e:
            if e.status_code != status.HTTP_429_TOO_MANY_REQUESTS:
                raise
            self._complete_stage(
                stage,
                "degraded",
                "Analisis AI dilewati karena kuota/rate limit (429).",
            )
            return (
                "Data berhasil diambil, namun analisis AI belum tersedia "
                "karena kuota/rate limit LLM tercapai."
                "Silakan coba lagi nanti."
            )

    def _run_graphic_generation_stage(
        self,
        stages: list[PipelineStageInfo],
        query_result: list[dict],
        chart_type: str,
        session_id: UUID,
    ) -> list[GraphicResult]:
        stage = self._start_stage(stages, "graphic_generation")
        try:
            results = graphic_service.generateGraphicPerKpi(
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

    async def _execute_sql(
        self, sql: str
    ) -> tuple[list[dict], int]:
        try:
            timeout_seconds = settings.SQL_EXECUTION_TIMEOUT

            async def _run_query() -> tuple[list[dict], int]:
                return await self.query_repo.execute_read_query(sql)

            return await asyncio.wait_for(_run_query(), timeout=timeout_seconds)

        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Eksekusi query melebihi batas waktu {settings.SQL_EXECUTION_TIMEOUT} detik.",
            )
        except Exception as e:
            logger.error(f"Error saat mengeksekusi SQL: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Query tidak dapat dieksekusi. Silakan coba pertanyaan yang berbeda.",
            ) from e
