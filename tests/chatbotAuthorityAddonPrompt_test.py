from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from model.Chatbot import AuthorityEnum, Chatbot
from repository.chatbotRepository import ChatbotRepository

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
