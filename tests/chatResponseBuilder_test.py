from uuid import uuid4

from schema.chatSchema import ChatResponse, PipelineStageInfo

from utils.responses.chatResponseBuilder import (
    AI_UNAVAILABLE_MESSAGE,
    SECURITY_BLOCKED_MESSAGE,
    build_ai_unavailable_response,
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)
from service.graphicService import GraphicResult


# ---------------------------------------------------------------------------
# build_clarification_prompt_message
# ---------------------------------------------------------------------------


def test_build_clarification_prompt_message_formats_questions():
    """Verifies the prompt includes the user query wrapped in single quotes
    and number-prefixed questions joined by newlines."""
    result = build_clarification_prompt_message(
        user_message="Tampilkan KPI",
        questions=["Periode mana?", "KPI mana?"],
    )

    expected = (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait "
        "'Tampilkan KPI', silakan jawab pertanyaan berikut.\n"
        "1. Periode mana?\n"
        "2. KPI mana?"
    )
    assert result == expected


def test_build_clarification_prompt_message_handles_single_question():
    result = build_clarification_prompt_message(
        user_message="Data penjualan",
        questions=["Tahun berapa?"],
    )

    expected = (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait "
        "'Data penjualan', silakan jawab pertanyaan berikut.\n"
        "1. Tahun berapa?"
    )
    assert result == expected


def test_build_clarification_prompt_message_handles_empty_questions():
    result = build_clarification_prompt_message(
        user_message="Data penjualan",
        questions=[],
    )

    expected = (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait "
        "'Data penjualan', silakan jawab pertanyaan berikut."
    )
    assert result == expected


# ---------------------------------------------------------------------------
# build_graphics_payload
# ---------------------------------------------------------------------------


def test_build_graphics_payload_empty_returns_none():
    assert build_graphics_payload([]) is None


def test_build_graphics_payload_normalizes_empty_kpi_name_to_none():
    results = [
        GraphicResult(chart_type="bar", image_url="/img/1.png", kpi_name=""),
    ]

    payload = build_graphics_payload(results)

    assert payload is not None
    assert len(payload) == 1
    assert isinstance(payload[0], dict)
    assert payload[0]["kpi_name"] is None
    assert payload[0]["chart_type"] == "bar"
    assert payload[0]["image_url"] == "/img/1.png"


def test_build_graphics_payload_preserves_non_empty_kpi_name():
    results = [
        GraphicResult(chart_type="line", image_url="/img/2.png", kpi_name="Revenue"),
    ]

    payload = build_graphics_payload(results)

    assert payload is not None
    assert len(payload) == 1
    assert payload[0]["kpi_name"] == "Revenue"


def test_build_graphics_payload_handles_multiple_results():
    results = [
        GraphicResult(chart_type="bar", image_url="/img/a.png", kpi_name=""),
        GraphicResult(chart_type="line", image_url="/img/b.png", kpi_name="Profit"),
    ]

    payload = build_graphics_payload(results)

    assert payload is not None
    assert len(payload) == 2
    assert payload[0]["kpi_name"] is None
    assert payload[1]["kpi_name"] == "Profit"


# ---------------------------------------------------------------------------
# build_security_blocked_response
# ---------------------------------------------------------------------------


def test_build_security_blocked_response():
    session_id = uuid4()
    stages = [
        PipelineStageInfo(stage="nl_to_sql", status="success", detail="ok"),
        PipelineStageInfo(
            stage="sql_validation", status="blocked", detail="DROP TABLE detected"
        ),
    ]

    response = build_security_blocked_response(session_id, stages)

    assert isinstance(response, ChatResponse)
    assert response.session_id == session_id
    assert response.message == SECURITY_BLOCKED_MESSAGE
    assert response.clarification_questions is None
    assert response.generated_sql is None
    assert response.graphics == []
    assert response.rows_returned is None
    assert response.execution_time_ms is None
    assert response.pipeline_stages == stages


# ---------------------------------------------------------------------------
# build_ai_unavailable_response
# ---------------------------------------------------------------------------


def test_build_ai_unavailable_response():
    session_id = uuid4()
    stages = [
        PipelineStageInfo(
            stage="nl_to_sql", status="degraded", detail="AI unavailable"
        ),
    ]

    response = build_ai_unavailable_response(session_id, stages)

    assert isinstance(response, ChatResponse)
    assert response.session_id == session_id
    assert response.message == AI_UNAVAILABLE_MESSAGE
    assert response.clarification_questions is None
    assert response.generated_sql is None
    assert response.graphics == []
    assert response.rows_returned is None
    assert response.execution_time_ms is None
    assert response.pipeline_stages == stages
