"""
Chat Service — Orchestrator Pipeline Structured RAG.
Menjalankan 4 stage secara berurutan:
    Stage 1: NL-to-SQL (GitHub Models)
  Stage 2: SQLWireguard Validation
  Stage 3: SQL Execution (PostgreSQL)
    Stage 4: Result Analysis (GitHub Models)
"""
import logging
import time
import uuid
import asyncio
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from config import get_settings
from service.llmService import GitHubModelsService
from service.sqlWireguardService import SQLWireguardService
from template.promptTemplate import build_nl_to_sql_prompt, build_analysis_prompt
from repository.chatbotAuditLogRepository import AuditLogRepository
from schema.chatSchema import ChatResponse, PipelineStageInfo

settings = get_settings()

llm = GitHubModelsService()
wireguard = SQLWireguardService()


class ChatService:
    """Orchestrator pipeline RAG untuk chatbot KPI."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_repo = AuditLogRepository(db)

    async def process_query(
        self,
        user_message: str,
        user_id: str,
        user_role: str,
        user_divisi: str | None,
        session_id: str | None,
        show_sql: bool = False,
        context_from_clarification: Any = None,
    ) -> ChatResponse:
        """
        Entry point utama. Jalankan pipeline dengan clarification mechanism:

        [STAGE 0 - BARU] Ambiguity Detection & Clarification
        [STAGE 1] NL-to-SQL (GitHub Models)
        [STAGE 2] SQLWireguard Validation
        [STAGE 3] SQL Execution (PostgreSQL)
        [STAGE 4] Result Analysis (GitHub Models)
        """
        from service.clarificationService import ClarificationService
        from utils.sessionContextManager import SessionContextManager

        session_id = session_id or str(uuid.uuid4())
        pipeline = self._build_pipeline_context(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            user_message=user_message,
        )
        stages: list[PipelineStageInfo] = []
        total_start = time.monotonic()

        try:
            # STAGE 0 — AMBIGUITY DETECTION & CLARIFICATION (BARU)
            clarification_stage = self._start_stage(
                stages, "Ambiguity Detection")

            # Skip stage 0 jika sudah ada clarification context (response dari user)
            if context_from_clarification is None:
                clarification_service = ClarificationService(self.db)
                clarification_count = await clarification_service.get_clarification_count_in_session(
                    session_id
                )

                clarification_response = await clarification_service.process_user_query(
                    user_query=user_message,
                    user_id=user_id,
                    user_role=user_role,
                    session_id=session_id,
                    clarification_count=clarification_count,
                )

                if clarification_response is not None:
                    # Pertanyaan klarifikasi diajukan → hentikan pipeline dan return
                    self._complete_stage(
                        clarification_stage, "completed", "Clarification question generated")

                    return ChatResponse(
                        session_id=session_id,
                        message=clarification_response.clarifying_question,
                        clarification_message_answer_options=clarification_response.options,
                        pipeline_stages=stages,
                    )
                else:
                    self._complete_stage(
                        clarification_stage, "completed", "No clarification needed")
            else:
                self._complete_stage(clarification_stage,
                                     "completed", "Using disambiguated query")
                # Update session context dengan jawaban klarifikasi
                SessionContextManager.get_session_context(session_id)

            # STAGE 1 — NL-TO-SQL
            generated_sql = await self._run_nl_to_sql_stage(
                stages=stages,
                user_message=user_message,
                user_id=user_id,
                user_role=user_role,
                user_divisi=user_divisi,
                pipeline=pipeline,
            )

            # STAGE 2 — SQL VALIDATION
            validation = self._run_sql_validation_stage(
                stages=stages,
                generated_sql=generated_sql,
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )
            if not validation.is_valid:
                await self._write_audit(pipeline)
                return ChatResponse(
                    session_id=session_id,
                    message=(
                        "Permintaan Anda tidak dapat diproses karena alasan keamanan. "
                        "Silakan ajukan pertanyaan yang berbeda tentang data KPI."
                    ),
                    pipeline_stages=stages,
                )

            sanitized_sql = validation.sanitized_sql

            # STAGE 3 — SQL EXECUTION
            query_result, rows_count = await self._run_sql_execution_stage(
                stages=stages,
                sanitized_sql=sanitized_sql,
                user_id=user_id,
                user_role=user_role,
                pipeline=pipeline,
            )

            # STAGE 4 — RESULT ANALYSIS
            narrative = await self._run_result_analysis_stage(
                stages=stages,
                user_query=user_message,
                executed_sql=sanitized_sql,
                query_result=query_result,
                rows_count=rows_count,
            )

            total_ms = int((time.monotonic() - total_start) * 1000)
            await self._write_audit(pipeline)

            return ChatResponse(
                session_id=session_id,
                message=narrative,
                generated_sql=sanitized_sql if show_sql else None,
                rows_returned=rows_count,
                execution_time_ms=total_ms,
                pipeline_stages=stages,
            )

        except Exception as error:
            raise await self._handle_pipeline_error(pipeline, error)

    @staticmethod
    def _build_pipeline_context(
        session_id: str,
        user_id: str,
        user_role: str,
        user_message: str,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "user_id": user_id,
            "user_role": user_role,
            "user_query": user_message,
            "generated_sql": None,
            "wireguard_status": None,
            "wireguard_reason": None,
            "execution_status": None,
            "rows_returned": None,
            "execution_time_ms": None,
        }

    @staticmethod
    def _start_stage(stages: list[PipelineStageInfo], stage_name: str) -> PipelineStageInfo:
        stage = PipelineStageInfo(stage=stage_name, status="running")
        stages.append(stage)
        return stage

    @staticmethod
    def _complete_stage(stage: PipelineStageInfo, status_value: str, detail: str) -> None:
        stage.status = status_value
        stage.detail = detail

    async def _handle_pipeline_error(
        self,
        pipeline: dict[str, Any],
        error: Exception,
    ) -> HTTPException:
        pipeline["execution_status"] = "error"
        await self._write_audit(pipeline)

        if isinstance(error, HTTPException):
            if error.status_code in (
                status.HTTP_408_REQUEST_TIMEOUT,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                status.HTTP_429_TOO_MANY_REQUESTS,
            ):
                return error

            if error.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
                logging.error(f"Error server saat memproses query: {error}")
                return HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Layanan chatbot sementara tidak tersedia. Silakan coba lagi.",
                )

            return HTTPException(
                status_code=error.status_code,
                detail="Permintaan tidak dapat diproses.",
            )

        logging.error(f"Error tidak terduga dalam memproses query: {error}")
        return HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Terjadi kesalahan saat memproses permintaan Anda. Silakan coba lagi.",
        )

    async def _run_nl_to_sql_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
        user_id: str,
        user_role: str,
        user_divisi: str | None,
        pipeline: dict[str, Any],
    ) -> str:
        stage = self._start_stage(stages, "nl_to_sql")
        nl_prompt = build_nl_to_sql_prompt(
            user_query=user_message,
            user_id=user_id,
            user_role=user_role,
            divisi=user_divisi,
        )
        generated_sql = await llm.generate_sql(nl_prompt)
        pipeline["generated_sql"] = generated_sql
        self._complete_stage(stage, "success", "SQL berhasil digenerate.")
        return generated_sql

    def _run_sql_validation_stage(
        self,
        stages: list[PipelineStageInfo],
        generated_sql: str,
        user_id: str,
        user_role: str,
        pipeline: dict[str, Any],
    ):
        stage = self._start_stage(stages, "sql_validation")
        validation = wireguard.validate(
            sql=generated_sql,
            user_id=user_id,
            user_role=user_role,
        )
        pipeline["wireguard_status"] = "PASS" if validation.is_valid else "FAIL"
        pipeline["wireguard_reason"] = validation.reason

        if validation.is_valid:
            self._complete_stage(
                stage, "success", "Query lolos validasi keamanan.")
        else:
            self._complete_stage(stage, "blocked", validation.reason)
        return validation

    async def _run_sql_execution_stage(
        self,
        stages: list[PipelineStageInfo],
        sanitized_sql: str,
        user_id: str,
        user_role: str,
        pipeline: dict[str, Any],
    ) -> tuple[list[dict], int]:
        stage = self._start_stage(stages, "sql_execution")
        exec_start = time.monotonic()

        logging.info(
            f"Menjalankan SQL untuk user_id={user_id} role={user_role}: {sanitized_sql}"
        )

        query_result, rows_count = await self._execute_sql(sanitized_sql)
        exec_ms = int((time.monotonic() - exec_start) * 1000)

        pipeline["execution_status"] = "success"
        pipeline["rows_returned"] = rows_count
        pipeline["execution_time_ms"] = exec_ms
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
    ) -> str:
        stage = self._start_stage(stages, "result_analysis")
        analysis_prompt = build_analysis_prompt(
            user_query=user_query,
            executed_sql=executed_sql,
            query_result=query_result,
            rows_count=rows_count,
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
                "karena kuota/rate limit GitHub Models tercapai. "
                "Silakan coba lagi nanti."
            )

    async def _execute_sql(
        self, sql: str
    ) -> tuple[list[dict], int]:
        """
        Eksekusi SQL ke PostgreSQL dengan timeout.
        Mengembalikan (list_of_rows, row_count).
        """
        try:
            timeout_seconds = settings.SQL_EXECUTION_TIMEOUT

            async def _run_query() -> tuple[list[dict], int]:
                result = await self.db.execute(text(sql))
                rows = result.mappings().all()
                data = [dict(row) for row in rows]
                return data, len(data)

            return await asyncio.wait_for(_run_query(), timeout=timeout_seconds)

        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail=f"Eksekusi query melebihi batas waktu {settings.SQL_EXECUTION_TIMEOUT} detik.",
            )
        except Exception as e:
            logging.error(f"Error saat mengeksekusi SQL: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Query tidak dapat dieksekusi. Silakan coba pertanyaan yang berbeda.",
            ) from e

    async def _write_audit(self, pipeline: dict) -> None:
        """Tulis hasil pipeline ke audit log (fire and forget — tidak raise error)."""
        try:
            await self.audit_repo.create(pipeline)
        except Exception:
            pass  # Audit log gagal tidak boleh mengganggu response utama

    async def get_audit_history(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 20,
    ):
        """Ambil riwayat query dari audit log untuk user tertentu."""
        import uuid as _uuid
        return await self.audit_repo.get_by_user(
            user_id=_uuid.UUID(user_id),
            skip=skip,
            limit=limit,
        )
