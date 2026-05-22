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
    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            return None

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)

    service = ChatService(db=None)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc:
        await service.process_query(
            user_message="Tampilkan KPI saya",
            user_id=UUID("00000000-0000-0000-0000-000000000401"),
            user_role="karyawan",
            user_divisi=None,
            session_id=None,
        )

    assert exc.value.status_code == 404
    assert "Tidak ada chatbot aktif" in exc.value.detail


async def test_process_query_resolves_chatbot_before_session_creation(monkeypatch):
    events = []

    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            events.append(("chatbot_lookup", authority))
            return SimpleNamespace(addon_prompt="Gunakan constraint bot.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
            events.append(("session_create", kwargs["session_id"]))

    class FakeClarificationService:
        def __init__(self, db):
            pass

        async def get_clarification_count_in_session(self, session_id):
            return 0

        async def process_user_query(self, **kwargs):
            return None

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr("service.clarificationService.ClarificationService", FakeClarificationService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", AsyncMock(return_value=("SELECT 1;", SimpleNamespace(is_visualize=False, chart_type=None))))
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=False, sanitized_sql=None, reason="blocked"))

    service = ChatService(db=None)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000402"),
        user_role="karyawan",
        user_divisi=None,
        session_id=None,
    )

    assert isinstance(response, ChatResponse)
    assert events[0][0] == "chatbot_lookup"
    assert events[1][0] == "session_create"


async def test_process_query_passes_addon_prompt_to_pipeline_stages(monkeypatch):
    captured = {}

    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            return SimpleNamespace(addon_prompt="Gunakan bahasa formal.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
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
        return "SELECT 1;", SimpleNamespace(is_visualize=False, chart_type=None)

    async def fake_analysis(self, **kwargs):
        captured["analysis_addon_prompt"] = kwargs.get("addon_prompt")
        return "Narasi hasil."

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr("service.clarificationService.ClarificationService", FakeClarificationService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", fake_nl_to_sql)
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=True, sanitized_sql="SELECT 1;", reason=None))
    monkeypatch.setattr(ChatService, "_run_sql_execution_stage", AsyncMock(return_value=([{"value": 1}], 1)))
    monkeypatch.setattr(ChatService, "_run_result_analysis_stage", fake_analysis)

    service = ChatService(db=None)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000403"),
        user_role="karyawan",
        user_divisi=None,
        session_id=UUID("00000000-0000-0000-0000-000000000404"),
    )

    assert response.message == "Narasi hasil."
    assert captured == {
        "clarification_addon_prompt": "Gunakan bahasa formal.",
        "nl_addon_prompt": "Gunakan bahasa formal.",
        "analysis_addon_prompt": "Gunakan bahasa formal.",
    }
