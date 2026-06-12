from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from databaseConfig import Base
from model.ChatMessage import ChatMessage
from model.ChatSession import ChatSession
from model.ClarificationAnswerOption import ClarificationAnswerOption
from model.ClarificationQuestion import ClarificationQuestion
from repository.chatMessageRepository import ChatMessageRepository


async def _make_sqlite_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_create_message_updates_session_end_at_to_message_send_at():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            session_id = uuid4()
            user_id = uuid4()
            session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                session_name="Test session",
            )
            db_session.add(session)
            await db_session.flush()

            repo = ChatMessageRepository(db_session)
            message = await repo.create(
                session_id=session_id,
                message="Halo",
                is_sender_chatbot=False,
            )

            await db_session.refresh(session)
            assert session.end_at == message.send_at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_detail_returns_messages_with_clarification_questions():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            session_id = uuid4()
            user_id = uuid4()
            session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                session_name="Test session",
            )
            db_session.add(session)
            await db_session.flush()

            user_message = ChatMessage(
                session_id=session_id,
                message="KPI saya gimana?",
                is_sender_chatbot=False,
            )
            bot_message = ChatMessage(
                session_id=session_id,
                message="KPI mana yang dimaksud?",
                is_sender_chatbot=True,
            )
            db_session.add_all([user_message, bot_message])
            await db_session.flush()

            question = ClarificationQuestion(
                message_id=user_message.message_id,
                ambiguity_type="level1",
                is_ambiguity_level1_type_llm=True,
                clarification_question="KPI mana yang dimaksud?",
            )
            db_session.add(question)
            await db_session.flush()
            db_session.add_all([
                ClarificationAnswerOption(clarification_question_id=question.clarification_question_id, option_text="Sales", option_order=0),
                ClarificationAnswerOption(clarification_question_id=question.clarification_question_id, option_text="HR", option_order=1),
            ])
            await db_session.commit()

            detail = await ChatMessageRepository(db_session).get_detail_by_session_id(session_id)

            assert detail is not None
            assert detail.session.session_id == session_id
            assert [message.message for message in detail.messages] == [
                "KPI saya gimana?",
                "KPI mana yang dimaksud?",
            ]
            loaded_question = detail.clarification_questions_by_message_id[user_message.message_id][0]
            assert loaded_question.clarification_question == "KPI mana yang dimaksud?"
            assert [option.option_text for option in loaded_question.answer_options] == ["Sales", "HR"]
            assert detail.clarification_questions_by_message_id.get(bot_message.message_id, []) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_first_by_session_id_returns_oldest_message_for_session():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            session_id = uuid4()
            user_id = uuid4()
            session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                session_name="first message test",
            )
            db_session.add(session)
            await db_session.flush()

            oldest = ChatMessage(
                session_id=session_id,
                message="first message",
                is_sender_chatbot=False,
            )
            oldest.send_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
            newer = ChatMessage(
                session_id=session_id,
                message="second message",
                is_sender_chatbot=False,
            )
            newer.send_at = datetime(2025, 6, 1, tzinfo=timezone.utc)
            db_session.add_all([oldest, newer])
            await db_session.commit()

            repo = ChatMessageRepository(db_session)
            result = await repo.get_first_by_session_id(session_id)

            assert result is not None
            assert result.message_id == oldest.message_id
            assert result.message == "first message"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_get_first_by_session_id_returns_none_when_session_has_no_messages():
    engine, session_factory = await _make_sqlite_session()
    try:
        async with session_factory() as db_session:
            session_id = uuid4()
            user_id = uuid4()
            session = ChatSession(
                session_id=session_id,
                user_id=user_id,
                session_name="empty session",
            )
            db_session.add(session)
            await db_session.commit()

            repo = ChatMessageRepository(db_session)
            result = await repo.get_first_by_session_id(session_id)

            assert result is None
    finally:
        await engine.dispose()
