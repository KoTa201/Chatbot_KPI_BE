import json
from unittest.mock import AsyncMock, Mock
from uuid import UUID


import pytest

SESSION_CLARIFY = UUID("00000000-0000-0000-0000-000000000001")
SESSION_BLOCKED = UUID("00000000-0000-0000-0000-000000000002")
SESSION_SUCCESS = UUID("00000000-0000-0000-0000-000000000003")
SESSION_VISUAL = UUID("00000000-0000-0000-0000-000000000004")
SESSION_RATE_LIMIT = UUID("00000000-0000-0000-0000-000000000005")
SESSION_TIMEOUT = UUID("00000000-0000-0000-0000-000000000006")
SESSION_LLM_DOWN = UUID("00000000-0000-0000-0000-000000000007")
from fastapi import HTTPException, status

import service.chatService as chat_service_module
from schema.clarificationSchema import ClarificationMessageResponse, ClarificationQuestionResponse
from schema.wireguardSchema import ValidationResult
from service.chatService import ChatService
from utils.dataClass.chatPipelineTypes import ChatPipelineContext
from service.graphicService import GraphicResult
from service.llmService import VisualizationDecision


async def _collect_sse_stream(stream) -> dict:
    """Collect SSE events from process_query_stream and return a dict
    with 'message', 'pipeline_stages', 'clarification_questions', etc."""
    metadata = {}
    message_parts: list[str] = []
    async for event in stream:
        event = event.strip()
        if not event:
            continue
        lines = event.split("\n")
        event_type = None
        data_str = None
        for line in lines:
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if event_type == "metadata" and data_str:
            metadata = json.loads(data_str)
        elif event_type == "message" and data_str:
            chunk_data = json.loads(data_str)
            message_parts.append(chunk_data.get("chunk", ""))
    metadata["message"] = "".join(message_parts)
    return metadata


async def _fake_analyze_stream(prompt: str):
    """Simple async generator that yields a single analysis string."""
    yield "Ini adalah analisa KPI."


def _patch_clarification_service(monkeypatch, clarification_response):
    class FakeClarificationService:
        def __init__(self, db):
            self.db = db

        async def get_clarification_count_in_session(self, session_id: UUID) -> int:
            return 0

        process_user_query = AsyncMock(return_value=clarification_response)

    import service.clarificationService as clarification_module

    monkeypatch.setattr(
        clarification_module,
        "ClarificationService",
        FakeClarificationService,
    )
    monkeypatch.setattr(
        chat_service_module,
        "ClarificationService",
        FakeClarificationService,
    )


def _create_chat_service(monkeypatch) -> ChatService:
    class FakeColumnStatisticsService:
        def __init__(self, db):
            self.db = db

        async def build_nl_to_sql_statistics(self):
            return ""

    monkeypatch.setattr(chat_service_module, "ColumnStatisticsService", FakeColumnStatisticsService)
    service = ChatService(db=Mock(commit=AsyncMock(), rollback=AsyncMock()))
    service.session_service = Mock()
    service.session_service.create_session_if_missing = AsyncMock(return_value=None)
    service.session_service.create_user_message = AsyncMock(
        return_value=Mock(message_id="00000000-0000-0000-0000-000000000301")
    )
    service.session_service.create_chatbot_message = AsyncMock(return_value=None)
    service.chatbot_service = Mock()
    service.chatbot_service.get_active_chatbot_for_role = AsyncMock(
        return_value=Mock(
            id=UUID("00000000-0000-0000-0000-000000000901"),
            addon_prompt="Prompt awal.",
        )
    )
    return service


def _stage_by_name(response, stage_name: str):
    """Supports both dict-based (SSE-collected) and object-based responses."""
    stages = response.get("pipeline_stages", []) if isinstance(response, dict) else response.pipeline_stages
    return next(
        (stage for stage in stages if (stage.get("stage") if isinstance(stage, dict) else stage.stage) == stage_name),
        None,
    )


@pytest.mark.asyncio
async def test_nl_to_sql_stage_only_generates_sql(monkeypatch):
    service = _create_chat_service(monkeypatch)
    sanitized_sql = "SELECT bulan, total_realisasi FROM report_kpi LIMIT 100;"
    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value=sanitized_sql))
    visualization_mock = AsyncMock(return_value=VisualizationDecision(is_visualize=True, chart_type="pie"))
    monkeypatch.setattr(chat_service_module.llm, "decide_visualization_request", visualization_mock)

    stages = []
    generated_sql = await service._run_nl_to_sql_stage(
        stages=stages,
        user_message="Tampilkan KPI bulan ini",
        user_id=UUID("00000000-0000-0000-0000-000000000302"),
        user_role="Owner",
        pipeline=ChatPipelineContext(
            session_id=UUID("00000000-0000-0000-0000-000000000302"),
            user_id=UUID("00000000-0000-0000-0000-000000000302"),
            user_role="Owner",
            user_query="Tampilkan KPI bulan ini",
        ),
        addon_prompt="Prompt awal.",
    )

    assert generated_sql == sanitized_sql
    visualization_mock.assert_not_awaited()
    assert stages[0].stage == "nl_to_sql"
    assert stages[0].status == "success"


@pytest.mark.asyncio
async def test_visualization_decision_stage_only_decides_visualization(monkeypatch):
    service = _create_chat_service(monkeypatch)
    sql_mock = AsyncMock(return_value="SELECT 1;")
    monkeypatch.setattr(chat_service_module.llm, "generate_sql", sql_mock)
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=True, chart_type="bar")),
    )

    stages = []
    decision = await service._run_visualization_decision_stage(
        stages=stages,
        user_message="Tampilkan KPI sebagai grafik",
    )

    assert decision.is_visualize is True
    assert decision.chart_type == "bar"
    sql_mock.assert_not_awaited()
    assert stages[0].stage == "visualization_decision"
    assert stages[0].status == "success"


@pytest.mark.asyncio
async def test_process_query_returns_clarification_when_query_is_ambiguous(monkeypatch):
    clarification_response = ClarificationMessageResponse(
        session_id=SESSION_CLARIFY,
        message_type="clarification",
        clarifying_question="Anda ingin data per individu atau per divisi?",
        options=["Per individu", "Per divisi"],
        questions=[
            ClarificationQuestionResponse(
                id="q-scope",
                ambiguity_type="AmbiSource",
                question="Anda ingin data per individu atau per divisi?",
                options=["Per individu", "Per divisi"],
            )
        ],
    )
    _patch_clarification_service(monkeypatch, clarification_response)

    generate_sql_mock = AsyncMock(return_value="SELECT 1")
    monkeypatch.setattr(chat_service_module.llm, "generate_sql", generate_sql_mock)
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=False, chart_type=None)),
    )

    service = _create_chat_service(monkeypatch)
    stream = service.process_query_stream(
        user_message="Siapa yang paling perform?",
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_role="Owner",
        session_id=SESSION_CLARIFY,
    )
    response = await _collect_sse_stream(stream)

    service.session_service.create_session_if_missing.assert_awaited_once_with(
        session_id=SESSION_CLARIFY,
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        first_message="Siapa yang paling perform?",
        chatbot_id=UUID("00000000-0000-0000-0000-000000000901"),
    )
    assert response["message"] == (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait 'Siapa yang paling perform?', silakan jawab pertanyaan berikut."
        "\n1. Anda ingin data per individu atau per divisi?"
    )
    assert response["clarification_questions"] is not None
    assert response["clarification_questions"][0]["options"] == ["Per individu", "Per divisi"]
    assert generate_sql_mock.await_count == 0
    clarification_call = service.clarification_service.process_user_query.await_args.kwargs
    assert isinstance(clarification_call["message_id"], UUID)

    assert len(response["pipeline_stages"]) == 1
    assert response["pipeline_stages"][0]["stage"] == "Ambiguity Detection"
    assert response["pipeline_stages"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_process_query_returns_security_message_when_sql_validation_fails(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value="SELECT * FROM users"))
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=False, chart_type=None)),
    )
    monkeypatch.setattr(
        chat_service_module.wireguard,
        "validate",
        lambda sql, user_id, user_role: ValidationResult(
            is_valid=False,
            reason="W-03: Tabel tidak diizinkan.",
            sanitized_sql=None,
        ),
    )

    service = _create_chat_service(monkeypatch)
    execute_sql_mock = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(service, "_run_sql_execution_stage", execute_sql_mock)

    stream = service.process_query_stream(
        user_message="Ambil semua data sensitif",
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        user_role="Owner",
        session_id=SESSION_BLOCKED,
    )
    response = await _collect_sse_stream(stream)

    assert "alasan keamanan" in response["message"].lower()
    assert execute_sql_mock.await_count == 0
    sql_validation_stage = _stage_by_name(response, "sql_validation")
    assert sql_validation_stage is not None
    assert sql_validation_stage["status"] == "blocked"


@pytest.mark.asyncio
async def test_process_query_success_without_visualization(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    sanitized_sql = "SELECT bulan, total_realisasi FROM report_kpi LIMIT 100;"
    query_rows = [{"bulan": 1, "total_realisasi": 120}]

    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value=sanitized_sql))
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=False, chart_type=None)),
    )
    monkeypatch.setattr(
        chat_service_module.llm,
        "analyze_result_stream",
        lambda prompt: _fake_analyze_stream(prompt),
    )
    monkeypatch.setattr(
        chat_service_module.wireguard,
        "validate",
        lambda sql, user_id, user_role: ValidationResult(
            is_valid=True,
            reason=None,
            sanitized_sql=sanitized_sql,
        ),
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(service, "_run_sql_execution_stage", AsyncMock(return_value=(query_rows, 1)))

    stream = service.process_query_stream(
        user_message="Tampilkan KPI bulan ini",
        user_id=UUID("00000000-0000-0000-0000-000000000003"),
        user_role="Owner",
        session_id=SESSION_SUCCESS,
        show_sql=True,
    )
    response = await _collect_sse_stream(stream)

    assert response["message"] == "Ini adalah analisa KPI."
    assert response["generated_sql"] == sanitized_sql
    assert response["graphics"] == []
    assert response["rows_returned"] == 1
    assert _stage_by_name(response, "graphic_generation") is None
    assert _stage_by_name(response, "result_analysis")["status"] == "running"


@pytest.mark.asyncio
async def test_process_query_success_with_visualization(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    sanitized_sql = "SELECT bulan, total_realisasi FROM report_kpi LIMIT 100;"
    query_rows = [
        {"bulan": 1, "total_realisasi": 120},
        {"bulan": 2, "total_realisasi": 90},
    ]

    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value=sanitized_sql))
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=True, chart_type="pie")),
    )
    monkeypatch.setattr(
        chat_service_module.llm,
        "analyze_result_stream",
        lambda prompt: _fake_analyze_stream(prompt),
    )
    monkeypatch.setattr(
        chat_service_module.wireguard,
        "validate",
        lambda sql, user_id, user_role: ValidationResult(
            is_valid=True,
            reason=None,
            sanitized_sql=sanitized_sql,
        ),
    )
    monkeypatch.setattr(
        chat_service_module.graphic_service,
        "generateGraphicPerKpi",
        lambda query_result, chart_type, session_id=None: [
            GraphicResult(
                chart_type=chart_type,
                image_url=f"/public/charts/{session_id}/chart-1.png",
            )
        ],
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(service, "_run_sql_execution_stage", AsyncMock(return_value=(query_rows, 2)))

    stream = service.process_query_stream(
        user_message="Tampilkan dalam bentuk pie chart",
        user_id=UUID("00000000-0000-0000-0000-000000000004"),
        user_role="Owner",
        session_id=SESSION_VISUAL,
    )
    response = await _collect_sse_stream(stream)

    expected_url = f"/public/charts/{SESSION_VISUAL}/chart-1.png"
    assert response["message"] == "Ini adalah analisa KPI."
    assert len(response["graphics"]) == 1
    assert response["graphics"][0]["chart_type"] == "pie"
    assert response["graphics"][0]["image_url"] == expected_url
    assert _stage_by_name(response, "graphic_generation")["status"] == "success"


@pytest.mark.asyncio
async def test_process_query_falls_back_when_analysis_rate_limited(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    sanitized_sql = "SELECT bulan, total_realisasi FROM report_kpi LIMIT 100;"
    query_rows = [{"bulan": 1, "total_realisasi": 120}]

    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value=sanitized_sql))
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=False, chart_type=None)),
    )

    async def _ratelimited_stream(prompt: str):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit",
        )
        yield  # unreachable, makes this an async generator

    monkeypatch.setattr(chat_service_module.llm, "analyze_result_stream", _ratelimited_stream)
    monkeypatch.setattr(
        chat_service_module.wireguard,
        "validate",
        lambda sql, user_id, user_role: ValidationResult(
            is_valid=True,
            reason=None,
            sanitized_sql=sanitized_sql,
        ),
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(service, "_run_sql_execution_stage", AsyncMock(return_value=(query_rows, 1)))

    stream = service.process_query_stream(
        user_message="Tampilkan KPI terbaru",
        user_id=UUID("00000000-0000-0000-0000-000000000005"),
        user_role="Owner",
        session_id=SESSION_RATE_LIMIT,
    )
    response = await _collect_sse_stream(stream)

    assert "rate limit" in response["message"].lower()
    assert _stage_by_name(response, "result_analysis")["status"] == "running"


@pytest.mark.asyncio
async def test_process_query_propagates_timeout_http_exception(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    sanitized_sql = "SELECT bulan, total_realisasi FROM report_kpi LIMIT 100;"
    monkeypatch.setattr(chat_service_module.llm, "generate_sql", AsyncMock(return_value=sanitized_sql))
    monkeypatch.setattr(
        chat_service_module.llm,
        "decide_visualization_request",
        AsyncMock(return_value=VisualizationDecision(is_visualize=False, chart_type=None)),
    )
    monkeypatch.setattr(
        chat_service_module.wireguard,
        "validate",
        lambda sql, user_id, user_role: ValidationResult(
            is_valid=True,
            reason=None,
            sanitized_sql=sanitized_sql,
        ),
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(
        service,
        "_run_sql_execution_stage",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="timeout",
            )
        ),
    )

    with pytest.raises(HTTPException) as error_info:
        stream = service.process_query_stream(
            user_message="Tampilkan KPI bulanan",
            user_id=UUID("00000000-0000-0000-0000-000000000006"),
            user_role="Owner",
            session_id=SESSION_TIMEOUT,
        )
        async for _ in stream:
            pass

    assert error_info.value.status_code == status.HTTP_408_REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_process_query_returns_fallback_message_when_llm_unavailable(monkeypatch):
    _patch_clarification_service(monkeypatch, clarification_response=None)

    monkeypatch.setattr(
        chat_service_module.llm,
        "generate_sql",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Layanan AI sementara tidak tersedia.",
            )
        ),
    )

    service = _create_chat_service(monkeypatch)

    stream = service.process_query_stream(
        user_message="Tampilkan KPI bulan ini",
        user_id=UUID("00000000-0000-0000-0000-000000000007"),
        user_role="Owner",
        session_id=SESSION_LLM_DOWN,
    )
    response = await _collect_sse_stream(stream)

    assert "sementara tidak tersedia" in response["message"].lower()
    nl_to_sql_stage = _stage_by_name(response, "nl_to_sql")
    assert nl_to_sql_stage is not None
    assert nl_to_sql_stage["status"] == "degraded"
