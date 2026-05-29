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
from service.graphicService import GraphicResult
from service.llmService import VisualizationDecision


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
    return next((stage for stage in response.pipeline_stages if stage.stage == stage_name), None)


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
        pipeline={},
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
    response = await service.process_query(
        user_message="Siapa yang paling perform?",
        user_id="user-1",
        user_role="Owner",
        session_id=SESSION_CLARIFY,
    )

    service.session_service.create_session_if_missing.assert_awaited_once_with(
        session_id=SESSION_CLARIFY,
        user_id="user-1",
        first_message="Siapa yang paling perform?",
        chatbot_id=UUID("00000000-0000-0000-0000-000000000901"),
    )
    assert response.message == "Anda ingin data per individu atau per divisi?"
    assert response.clarification_questions is not None
    assert response.clarification_questions[0].options == ["Per individu", "Per divisi"]
    assert not hasattr(response, "clarification_message_answer_options")
    assert generate_sql_mock.await_count == 0
    clarification_call = service.clarification_service.process_user_query.await_args.kwargs
    assert isinstance(clarification_call["message_id"], UUID)

    assert len(response.pipeline_stages) == 1
    assert response.pipeline_stages[0].stage == "Ambiguity Detection"
    assert response.pipeline_stages[0].status == "completed"


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
    monkeypatch.setattr(service, "_execute_sql", execute_sql_mock)

    response = await service.process_query(
        user_message="Ambil semua data sensitif",
        user_id="user-2",
        user_role="Owner",
        session_id=SESSION_BLOCKED,
    )

    assert "alasan keamanan" in response.message.lower()
    assert execute_sql_mock.await_count == 0
    sql_validation_stage = _stage_by_name(response, "sql_validation")
    assert sql_validation_stage is not None
    assert sql_validation_stage.status == "blocked"


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
        "analyze_result",
        AsyncMock(return_value="Ini adalah analisa KPI."),
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
    monkeypatch.setattr(service, "_execute_sql", AsyncMock(return_value=(query_rows, 1)))

    response = await service.process_query(
        user_message="Tampilkan KPI bulan ini",
        user_id="user-3",
        user_role="Owner",
        session_id=SESSION_SUCCESS,
        show_sql=True,
    )

    assert response.message == "Ini adalah analisa KPI."
    assert response.generated_sql == sanitized_sql
    assert response.graphic_chart_type is None
    assert response.graphic_image_url is None
    assert response.rows_returned == 1
    assert _stage_by_name(response, "graphic_generation") is None
    assert _stage_by_name(response, "result_analysis").status == "success"


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
        "analyze_result",
        AsyncMock(return_value="Analisa dengan grafik."),
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
        "generateGraphic",
        lambda query_result, chart_type, session_id=None: GraphicResult(
            chart_type=chart_type,
            image_url=f"/public/charts/{session_id}/chart-1.png",
        ),
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(service, "_execute_sql", AsyncMock(return_value=(query_rows, 2)))

    response = await service.process_query(
        user_message="Tampilkan dalam bentuk pie chart",
        user_id="user-4",
        user_role="Owner",
        session_id=SESSION_VISUAL,
    )

    expected_url = f"/public/charts/{SESSION_VISUAL}/chart-1.png"
    assert response.message == f"Analisa dengan grafik.\n\nGrafik: {expected_url}"
    assert response.graphic_chart_type == "pie"
    assert response.graphic_image_url == expected_url
    assert _stage_by_name(response, "graphic_generation").status == "success"


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
    monkeypatch.setattr(
        chat_service_module.llm,
        "analyze_result",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit",
            )
        ),
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
    monkeypatch.setattr(service, "_execute_sql", AsyncMock(return_value=(query_rows, 1)))

    response = await service.process_query(
        user_message="Tampilkan KPI terbaru",
        user_id="user-5",
        user_role="Owner",
        session_id=SESSION_RATE_LIMIT,
    )

    assert "rate limit" in response.message.lower()
    assert _stage_by_name(response, "result_analysis").status == "degraded"


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
        "_execute_sql",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="timeout",
            )
        ),
    )

    with pytest.raises(HTTPException) as error_info:
        await service.process_query(
            user_message="Tampilkan KPI bulanan",
            user_id="user-6",
            user_role="Owner",
                session_id=SESSION_TIMEOUT,
        )

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

    response = await service.process_query(
        user_message="Tampilkan KPI bulan ini",
        user_id="user-7",
        user_role="Owner",
        session_id=SESSION_LLM_DOWN,
    )

    assert "sementara tidak tersedia" in response.message.lower()
    nl_to_sql_stage = _stage_by_name(response, "nl_to_sql")
    assert nl_to_sql_stage is not None
    assert nl_to_sql_stage.status == "degraded"
