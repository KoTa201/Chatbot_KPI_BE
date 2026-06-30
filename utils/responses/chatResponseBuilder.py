"""
service/chatResponseBuilder.py
Stateless pure functions for building chat response payloads.

Extracted from chatService.py as part of the service refactor to
improve cohesion and testability — these functions have no side
effects and no I/O.
"""

from uuid import UUID
from schema.chatSchema import ChatResponse, PipelineStageInfo, GraphicItemResponse
from service.graphicService import GraphicResult
from utils.helper.sseHelpers import format_sse_metadata
from utils.helper.pipelineStageHelpers import (
    complete_stage
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AI_UNAVAILABLE_MESSAGE = (
    "Layanan AI sementara tidak tersedia. Silakan coba lagi."
)

SECURITY_BLOCKED_MESSAGE = (
    "Permintaan Anda tidak dapat diproses karena alasan keamanan. "
    "Silakan ajukan pertanyaan yang berbeda tentang data KPI."
)


# ---------------------------------------------------------------------------
# Clarification prompt
# ---------------------------------------------------------------------------


def build_clarification_prompt_message(
    user_message: str,
    questions: list[str],
) -> str:
    """Build the single-message clarification prompt shown to the user.

    Format: "Terdapat beberapa pertanyaan yang ingin saya tanyakan
    terkait '<user_message>', silakan jawab pertanyaan berikut.\\n
    1. <q1>\\n2. <q2>..."
    """
    numbered = "\n".join(
        f"{i}. {q}" for i, q in enumerate(questions, start=1)
    )
    suffix = f"\n{numbered}" if numbered else ""
    return (
        f"Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait "
        f"'{user_message}', silakan jawab pertanyaan berikut."
        f"{suffix}"
    )


# ---------------------------------------------------------------------------
# Graphics payload
# ---------------------------------------------------------------------------


def build_graphics_payload(
    graphic_results: list[GraphicResult],
) -> list[dict[str, str | None]] | None:
    """Convert a list of GraphicResult objects into a list of dicts
    suitable for chat session persistence.

    Returns None when the input list is empty.
    Normalises empty-string kpi_name to None.
    """
    if not graphic_results:
        return None

    return [
        {
            "kpi_name": r.kpi_name or None,
            "chart_type": r.chart_type,
            "image_url": r.image_url,
        }
        for r in graphic_results
    ]


# ---------------------------------------------------------------------------
# Error / fallback responses
# ---------------------------------------------------------------------------


def build_security_blocked_response(
    session_id: UUID,
    pipeline_stages: list[PipelineStageInfo],
) -> ChatResponse:
    """Build a ChatResponse indicating the query was blocked by the
    SQL wireguard."""
    return ChatResponse(
        session_id=session_id,
        message=SECURITY_BLOCKED_MESSAGE,
        pipeline_stages=pipeline_stages,
    )


def build_ai_unavailable_response(
    session_id: UUID,
    pipeline_stages: list[PipelineStageInfo],
) -> ChatResponse:
    """Build a ChatResponse indicating the AI service is unavailable."""
    return ChatResponse(
        session_id=session_id,
        message=AI_UNAVAILABLE_MESSAGE,
        pipeline_stages=pipeline_stages,
    )

def _build_metadata_event(
        session_id: UUID,
        sanitized_sql: str,
        graphic_results: list[GraphicResult],
        rows_count: int,
        total_ms: int,
        stages: list[PipelineStageInfo],
        query_result: list[dict],
        show_sql: bool = False,
) -> str:
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
    return format_sse_metadata(metadata)

async def _handle_no_data(
        analysis_stage,
        prefix: str,
) -> str:
    fallback = prefix + "Mohon maaf, tidak ada data valid untuk pertanyaan anda atau pertanyaan anda diluar konteks domain sistem ini."
    complete_stage(analysis_stage, "success", "Tidak ada data ditemukan.")
    return fallback

def _handle_unsupported_visualization_type(visualization_decision) -> str | None:
    if not visualization_decision.is_visualize:
        return None

    req_type = (visualization_decision.chart_type or "").strip().lower()
    supported_types = {"bar", "batang", "donut", "donat", "line", "garis"}
    if req_type in supported_types:
        return None

    visualization_decision.is_visualize = False
    return f"⚠️ **Maaf, tipe grafik '{visualization_decision.chart_type}' tidak didukung oleh sistem.** Sistem saat ini hanya mendukung grafik **Batang**, **Donat**, dan **Garis**.\n\nBerikut adalah data dalam bentuk teks:\n\n"
