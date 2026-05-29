from types import SimpleNamespace
from uuid import UUID
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from fastapi import HTTPException

from model.Chatbot import AuthorityEnum, Chatbot
from repository.chatbotRepository import ChatbotRepository
import service.chatService as chat_service_module
from service.chatService import ChatService
from schema.chatSchema import ChatResponse

pytestmark = pytest.mark.asyncio

CHATBOT_ID = UUID("00000000-0000-0000-0000-000000000301")


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return FakeScalarResult(self.value)


class FakeDb:
    def __init__(self, value):
        self.value = value
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.value)


async def test_get_active_by_authority_returns_matching_active_chatbot():
    chatbot = SimpleNamespace(
        id=CHATBOT_ID,
        authority=AuthorityEnum.KARYAWAN,
        is_active=True,
        addon_prompt="Gunakan bahasa singkat.",
    )
    db = FakeDb(chatbot)
    repo = ChatbotRepository(db)  # type: ignore[arg-type]

    result = await repo.get_active_by_authority(AuthorityEnum.KARYAWAN)

    assert result is chatbot
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "chatbots.authority = 'karyawan'" in compiled
    assert "chatbots.is_active = true" in compiled.lower()


async def test_get_active_by_authority_accepts_role_string():
    chatbot = SimpleNamespace(authority=AuthorityEnum.KEPALA_DIVISI, is_active=True)
    db = FakeDb(chatbot)
    repo = ChatbotRepository(db)  # type: ignore[arg-type]

    result = await repo.get_active_by_authority("kepala_divisi")

    assert result is chatbot
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "chatbots.authority = 'kepala_divisi'" in compiled


async def test_process_query_fails_when_no_active_chatbot(monkeypatch):
    class FakeChatbotService:
        def __init__(self, db):
            pass

        async def get_active_chatbot_for_role(self, user_role):
            raise HTTPException(
                status_code=404,
                detail="Tidak ada chatbot aktif yang dikonfigurasi untuk authority user ini.",
            )

    monkeypatch.setattr(chat_service_module, "ChatbotService", FakeChatbotService)

    service = ChatService(db=None)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc:
        await service.process_query(
            user_message="Tampilkan KPI saya",
            user_id=UUID("00000000-0000-0000-0000-000000000401"),
            user_role="karyawan",
            session_id=None,
        )

    assert exc.value.status_code == 404
    assert "Tidak ada chatbot aktif" in exc.value.detail


async def test_process_query_resolves_chatbot_before_session_creation(monkeypatch):
    events = []

    class FakeChatbotService:
        def __init__(self, db):
            pass

        async def get_active_chatbot_for_role(self, user_role):
            events.append(("chatbot_lookup", user_role))
            return SimpleNamespace(id=CHATBOT_ID, addon_prompt="Gunakan constraint bot.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
            events.append(("session_create", kwargs["session_id"]))

        async def create_user_message(self, **kwargs):
            return SimpleNamespace(message_id="00000000-0000-0000-0000-000000000411")

        async def create_chatbot_message(self, **kwargs):
            return None

    class FakeClarificationService:
        def __init__(self, db):
            pass

        async def get_clarification_count_in_session(self, session_id):
            return 0

        async def process_user_query(self, **kwargs):
            return None

    monkeypatch.setattr(chat_service_module, "ChatbotService", FakeChatbotService)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr(chat_service_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", AsyncMock(return_value="SELECT 1;"))
    monkeypatch.setattr(ChatService, "_run_visualization_decision_stage", AsyncMock(return_value=SimpleNamespace(is_visualize=False, chart_type=None)))
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=False, sanitized_sql=None, reason="blocked"))

    service = ChatService(db=None)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000402"),
        user_role="karyawan",
        session_id=None,
    )

    assert isinstance(response, ChatResponse)
    assert events[0][0] == "chatbot_lookup"
    assert events[1][0] == "session_create"


async def test_process_query_passes_addon_prompt_to_pipeline_stages(monkeypatch):
    captured = {}

    class FakeChatbotService:
        def __init__(self, db):
            pass

        async def get_active_chatbot_for_role(self, user_role):
            return SimpleNamespace(id=CHATBOT_ID, addon_prompt="Gunakan bahasa formal.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
            return None

        async def create_user_message(self, **kwargs):
            return SimpleNamespace(message_id="00000000-0000-0000-0000-000000000411")

        async def create_chatbot_message(self, **kwargs):
            return None

    class FakeClarificationService:
        def __init__(self, db):
            pass

        async def get_clarification_count_in_session(self, session_id):
            return 0

        async def process_user_query(self, **kwargs):
            captured["clarification_addon_prompt"] = kwargs.get("addon_prompt")
            return None

    async def fake_nl_to_sql(self, **kwargs):
        captured["nl_addon_prompt"] = kwargs.get("addon_prompt")
        return "SELECT 1;"

    async def fake_analysis(self, **kwargs):
        captured["analysis_addon_prompt"] = kwargs.get("addon_prompt")
        return "Narasi hasil."

    monkeypatch.setattr(chat_service_module, "ChatbotService", FakeChatbotService)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr(chat_service_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", fake_nl_to_sql)
    monkeypatch.setattr(ChatService, "_run_visualization_decision_stage", AsyncMock(return_value=SimpleNamespace(is_visualize=False, chart_type=None)))
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=True, sanitized_sql="SELECT 1;", reason=None))
    monkeypatch.setattr(ChatService, "_run_sql_execution_stage", AsyncMock(return_value=([{"value": 1}], 1)))
    monkeypatch.setattr(ChatService, "_run_result_analysis_stage", fake_analysis)

    from unittest.mock import AsyncMock as UM
    mock_db = SimpleNamespace(commit=UM(), rollback=UM())
    service = ChatService(db=mock_db)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000403"),
        user_role="karyawan",
        session_id=UUID("00000000-0000-0000-0000-000000000404"),
    )

    assert response.message == "Narasi hasil."
    assert captured == {
        "clarification_addon_prompt": "Gunakan bahasa formal.",
        "nl_addon_prompt": "Gunakan bahasa formal.",
        "analysis_addon_prompt": "Gunakan bahasa formal.",
    }


async def test_run_nl_to_sql_stage_passes_addon_prompt_to_builder(monkeypatch):
    """Verify _run_nl_to_sql_stage passes addon_prompt to build_nl_to_sql_prompt."""
    class FakeColumnStatisticsService:
        def __init__(self, db):
            self.db = db

        async def build_nl_to_sql_statistics(self):
            return ""

    monkeypatch.setattr("service.chatService.ColumnStatisticsService", FakeColumnStatisticsService)
    captured_builder_args = {}

    def fake_build_nl_to_sql_prompt(**kwargs):
        captured_builder_args.update(kwargs)
        return "SELECT 1;"

    async def fake_generate_sql(prompt):
        return "SELECT 1;"

    async def fake_decide_visualization(prompt):
        return SimpleNamespace(is_visualize=False, chart_type=None)

    monkeypatch.setattr(
        "service.chatService.build_nl_to_sql_prompt",
        fake_build_nl_to_sql_prompt,
    )
    monkeypatch.setattr(
        "service.chatService.llm.generate_sql",
        fake_generate_sql,
    )
    monkeypatch.setattr(
        "service.chatService.llm.decide_visualization_request",
        fake_decide_visualization,
    )

    service = ChatService(db=None)  # type: ignore[arg-type]
    stages = []
    addon_prompt_value = "Gunakan format ringkas."

    generated_sql = await service._run_nl_to_sql_stage(
        stages=stages,
        user_message="Berapa KPI Q1?",
        user_id=UUID("00000000-0000-0000-0000-000000000501"),
        user_role="karyawan",
        pipeline={},
        addon_prompt=addon_prompt_value,
    )

    assert generated_sql == "SELECT 1;"
    assert captured_builder_args["addon_prompt"] == addon_prompt_value
    assert captured_builder_args["user_query"] == "Berapa KPI Q1?"
    assert captured_builder_args["user_role"] == "karyawan"


async def test_run_nl_to_sql_stage_passes_column_statistics_to_builder(monkeypatch):
    captured_builder_args = {}

    def fake_build_nl_to_sql_prompt(**kwargs):
        captured_builder_args.update(kwargs)
        return "SELECT 1;"

    async def fake_generate_sql(prompt):
        return "SELECT 1;"

    async def fake_decide_visualization(prompt):
        return SimpleNamespace(is_visualize=False, chart_type=None)

    class FakeColumnStatisticsService:
        def __init__(self, db):
            self.db = db

        async def build_nl_to_sql_statistics(self):
            return "kpi_tracker_records.bulan_num: mean=3.5"

    monkeypatch.setattr(
        "service.chatService.build_nl_to_sql_prompt",
        fake_build_nl_to_sql_prompt,
    )
    monkeypatch.setattr(
        "service.chatService.llm.generate_sql",
        fake_generate_sql,
    )
    monkeypatch.setattr(
        "service.chatService.llm.decide_visualization_request",
        fake_decide_visualization,
    )
    monkeypatch.setattr(
        "service.chatService.ColumnStatisticsService",
        FakeColumnStatisticsService,
    )

    service = ChatService(db=None)  # type: ignore[arg-type]
    stages = []

    await service._run_nl_to_sql_stage(
        stages=stages,
        user_message="Berapa KPI Q1?",
        user_id=UUID("00000000-0000-0000-0000-000000000503"),
        user_role="karyawan",
        pipeline={},
        addon_prompt=None,
    )

    assert captured_builder_args["column_statistics"] == "kpi_tracker_records.bulan_num: mean=3.5"


async def test_run_nl_to_sql_stage_passes_none_addon_prompt_to_builder(monkeypatch):
    """Verify _run_nl_to_sql_stage passes None addon_prompt when not provided."""
    class FakeColumnStatisticsService:
        def __init__(self, db):
            self.db = db

        async def build_nl_to_sql_statistics(self):
            return ""

    monkeypatch.setattr("service.chatService.ColumnStatisticsService", FakeColumnStatisticsService)
    captured_builder_args = {}

    def fake_build_nl_to_sql_prompt(**kwargs):
        captured_builder_args.update(kwargs)
        return "SELECT 1;"

    async def fake_generate_sql(prompt):
        return "SELECT 1;"

    async def fake_decide_visualization(prompt):
        return SimpleNamespace(is_visualize=False, chart_type=None)

    monkeypatch.setattr(
        "service.chatService.build_nl_to_sql_prompt",
        fake_build_nl_to_sql_prompt,
    )
    monkeypatch.setattr(
        "service.chatService.llm.generate_sql",
        fake_generate_sql,
    )
    monkeypatch.setattr(
        "service.chatService.llm.decide_visualization_request",
        fake_decide_visualization,
    )

    service = ChatService(db=None)  # type: ignore[arg-type]
    stages = []

    generated_sql = await service._run_nl_to_sql_stage(
        stages=stages,
        user_message="Berapa KPI Q1?",
        user_id=UUID("00000000-0000-0000-0000-000000000502"),
        user_role="karyawan",
        pipeline={},
        addon_prompt=None,
    )

    assert generated_sql == "SELECT 1;"
    assert captured_builder_args["addon_prompt"] is None


async def test_run_result_analysis_stage_passes_addon_prompt_to_builder(monkeypatch):
    """Verify _run_result_analysis_stage passes addon_prompt to build_analysis_prompt."""
    captured_builder_args = {}

    def fake_build_analysis_prompt(**kwargs):
        captured_builder_args.update(kwargs)
        return "Analisis prompt"

    async def fake_analyze_result(prompt):
        return "Hasil analisis."

    monkeypatch.setattr(
        "service.chatService.build_analysis_prompt",
        fake_build_analysis_prompt,
    )
    monkeypatch.setattr(
        "service.chatService.llm.analyze_result",
        fake_analyze_result,
    )

    service = ChatService(db=None)  # type: ignore[arg-type]
    stages = []
    addon_prompt_value = "Gunakan format ringkas."
    query_result = [{"kpi": "Revenue", "value": 1000}]

    narrative = await service._run_result_analysis_stage(
        stages=stages,
        user_query="Berapa revenue?",
        executed_sql="SELECT * FROM kpi;",
        query_result=query_result,
        rows_count=1,
        addon_prompt=addon_prompt_value,
    )

    assert narrative == "Hasil analisis."
    assert captured_builder_args["addon_prompt"] == addon_prompt_value
    assert captured_builder_args["user_query"] == "Berapa revenue?"
    assert captured_builder_args["executed_sql"] == "SELECT * FROM kpi;"
    assert captured_builder_args["query_result"] == query_result
    assert captured_builder_args["rows_count"] == 1


async def test_run_result_analysis_stage_passes_none_addon_prompt_to_builder(monkeypatch):
    """Verify _run_result_analysis_stage passes None addon_prompt when not provided."""
    captured_builder_args = {}

    def fake_build_analysis_prompt(**kwargs):
        captured_builder_args.update(kwargs)
        return "Analisis prompt"

    async def fake_analyze_result(prompt):
        return "Hasil analisis."

    monkeypatch.setattr(
        "service.chatService.build_analysis_prompt",
        fake_build_analysis_prompt,
    )
    monkeypatch.setattr(
        "service.chatService.llm.analyze_result",
        fake_analyze_result,
    )

    service = ChatService(db=None)  # type: ignore[arg-type]
    stages = []
    query_result = [{"kpi": "Revenue", "value": 1000}]

    narrative = await service._run_result_analysis_stage(
        stages=stages,
        user_query="Berapa revenue?",
        executed_sql="SELECT * FROM kpi;",
        query_result=query_result,
        rows_count=1,
        addon_prompt=None,
    )

    assert narrative == "Hasil analisis."
    assert captured_builder_args["addon_prompt"] is None
