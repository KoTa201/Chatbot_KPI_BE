"""Stateless helpers for the chat RAG pipeline.

Extracted from service/chatService.py so the orchestrator keeps only flow logic;
these are pure functions over pipeline stages, ids, and error mapping.
"""

import logging
from uuid import UUID

from fastapi import HTTPException, status

from schema.chatSchema import PipelineStageInfo
from utils.dataClass.chatPipelineTypes import ChatPipelineContext

logger = logging.getLogger(__name__)


def build_pipeline_context(
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


def coerce_message_id(message_id: UUID | str) -> UUID:
    return message_id if isinstance(message_id, UUID) else UUID(str(message_id))


def start_stage(stages: list[PipelineStageInfo], stage_name: str) -> PipelineStageInfo:
    stage = PipelineStageInfo(stage=stage_name, status="running")
    stages.append(stage)
    return stage


def complete_stage(stage: PipelineStageInfo, status_value: str, detail: str) -> None:
    stage.status = status_value
    stage.detail = detail


def map_pipeline_error(pipeline: ChatPipelineContext, error: Exception) -> HTTPException:
    """Map any pipeline exception to a user-safe HTTPException."""
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
