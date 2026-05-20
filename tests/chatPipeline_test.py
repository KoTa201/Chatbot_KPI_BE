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
from schema.clarificationSchema import ClarificationMessageResponse
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

        async def process_user_query(
            self,
            user_query: str,
            user_id: str,
            user_role: str,
            session_id: UUID,
            clarification_count: int = 0,
        ):
            return clarification_response

    import service.clarificationService as clarification_module

    monkeypatch.setattr(
        clarification_module,
        "ClarificationService",
        FakeClarificationService,
    )


def _create_chat_service(monkeypatch) -> ChatService:
    service = ChatService(db=None)
    service.session_service = Mock()
    service.session_service.create_session_if_missing = AsyncMock(return_value=None)
    return service


def _stage_by_name(response, stage_name: str):
    return next((stage for stage in response.pipeline_stages if stage.stage == stage_name), None)


@pytest.mark.asyncio
async def test_process_query_returns_clarification_when_query_is_ambiguous(monkeypatch):
    clarification_response = ClarificationMessageResponse(
        session_id=SESSION_CLARIFY,
        message_type="clarification",
        clarifying_question="Anda ingin data per individu atau per divisi?",
        options=["Per individu", "Per divisi"],
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
        user_divisi=None,
        session_id=SESSION_CLARIFY,
    )

    assert response.message == "Anda ingin data per individu atau per divisi?"
    assert response.clarification_message_answer_options == ["Per individu", "Per divisi"]
    assert generate_sql_mock.await_count == 0
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
        user_divisi=None,
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
        user_divisi=None,
        session_id=SESSION_SUCCESS,
        show_sql=True,
    )

    assert response.message == "Ini adalah analisa KPI."
    assert response.generated_sql == sanitized_sql
    assert response.graphic_chart_type is None
    assert response.graphic_image_base64 is None
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
        lambda query_result, chart_type: GraphicResult(
            chart_type=chart_type,
            image_base64="BASE64_IMAGE_CONTENT",
        ),
    )

    service = _create_chat_service(monkeypatch)
    monkeypatch.setattr(service, "_execute_sql", AsyncMock(return_value=(query_rows, 2)))

    response = await service.process_query(
        user_message="Tampilkan dalam bentuk pie chart",
        user_id="user-4",
        user_role="Owner",
        user_divisi=None,
        session_id=SESSION_VISUAL,
    )

    assert response.message == "Analisa dengan grafik."
    assert response.graphic_chart_type == "pie"
    assert response.graphic_image_base64 == "BASE64_IMAGE_CONTENT"
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
        user_divisi=None,
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
            user_divisi=None,
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
        user_divisi=None,
        session_id=SESSION_LLM_DOWN,
    )

    assert "sementara tidak tersedia" in response.message.lower()
    nl_to_sql_stage = _stage_by_name(response, "nl_to_sql")
    assert nl_to_sql_stage is not None
    assert nl_to_sql_stage.status == "degraded"
