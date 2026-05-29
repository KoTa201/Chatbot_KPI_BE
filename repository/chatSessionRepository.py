import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.ChatMessage import ChatMessage
from model.ChatSession import ChatSession
from model.ClarificationQuestion import ClarificationQuestion
from utils.datetime import utc_now


@dataclass
class ChatSessionDetailRecord:
    session: ChatSession
    messages: list[ChatMessage]
    clarification_questions_by_message_id: dict[uuid.UUID, list[ClarificationQuestion]]


class ChatSessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str,
        chatbot_id: uuid.UUID | None = None,
    ) -> ChatSession:
        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            session_name=title[:80].strip() or "New Chat",
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def create_message(
        self,
        session_id: uuid.UUID,
        message: str,
        is_sender_chatbot: bool,
    ) -> ChatMessage:
        chat_message = ChatMessage(
            session_id=session_id,
            message=message,
            is_sender_chatbot=is_sender_chatbot,
        )
        self.db.add(chat_message)
        await self.db.flush()

        session = await self.get_by_id(session_id)
        if session is not None:
            session.end_at = chat_message.send_at
            await self.db.flush()

        await self.db.refresh(chat_message)
        return chat_message

    async def get_by_user(self, user_id: uuid.UUID) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.start_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def get_detail_by_id(self, session_id: uuid.UUID) -> ChatSessionDetailRecord | None:
        session = await self.get_by_id(session_id)
        if session is None:
            return None

        messages_result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.send_at.asc())
        )
        messages = list(messages_result.scalars().all())

        questions_result = await self.db.execute(
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id)
            .where(ClarificationQuestion.message_id.is_not(None))
            .order_by(ClarificationQuestion.created_at.asc())
        )
        questions_by_message_id: dict[uuid.UUID, list[ClarificationQuestion]] = {}
        for question in questions_result.scalars().all():
            if question.message_id is None:
                continue
            questions_by_message_id.setdefault(question.message_id, []).append(question)

        return ChatSessionDetailRecord(
            session=session,
            messages=messages,
            clarification_questions_by_message_id=questions_by_message_id,
        )

    async def update_title(self, session: ChatSession, title: str) -> Optional[ChatSession]:
        session.session_name = title
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def end_session(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.end_at = utc_now()
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def delete(self, session: ChatSession):
        await self.db.delete(session)
        await self.db.flush()
