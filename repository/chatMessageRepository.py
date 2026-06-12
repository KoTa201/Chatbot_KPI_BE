import asyncio
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.ChatMessage import ChatMessage
from model.ChatMessageGraphic import ChatMessageGraphic
from model.ChatSession import ChatSession
from model.ClarificationQuestion import ClarificationQuestion


@dataclass
class ChatSessionDetailRecord:
    session: ChatSession
    messages: list[ChatMessage]
    clarification_questions_by_message_id: dict[uuid.UUID, list[ClarificationQuestion]]
    graphics_by_message_id: dict[uuid.UUID, list[ChatMessageGraphic]]


class ChatMessageRepository:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def create(
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

        session = await self._get_session_by_id(session_id)
        if session is not None:
            session.end_at = chat_message.send_at
            await self.db.flush()

        await self.db.refresh(chat_message)
        return chat_message

    async def create_graphics(
        self,
        message_id: uuid.UUID,
        graphics: list[dict],
    ) -> None:
        for order, g in enumerate(graphics):
            self.db.add(ChatMessageGraphic(
                message_id=message_id,
                kpi_name=g.get("kpi_name"),
                chart_type=g["chart_type"],
                image_url=g["image_url"],
                display_order=order,
            ))
        await self.db.flush()

    async def get_detail_by_session_id(self, session_id: uuid.UUID) -> ChatSessionDetailRecord | None:
        session = await self._get_session_by_id(session_id)
        if session is None:
            return None

        messages_result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.send_at.asc())
        )

        questions_result = await self.db.execute(
            select(ClarificationQuestion)
            .options(selectinload(ClarificationQuestion.answer_options))
            .join(ChatMessage, ClarificationQuestion.message_id == ChatMessage.message_id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ClarificationQuestion.created_at.asc())
        )

        graphics_result = await self.db.execute(
            select(ChatMessageGraphic)
            .join(ChatMessage, ChatMessageGraphic.message_id == ChatMessage.message_id)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessageGraphic.message_id, ChatMessageGraphic.display_order)
        )

        messages = messages_result.scalars().all()

        questions_by_message_id: dict[uuid.UUID, list[ClarificationQuestion]] = {}
        for question in questions_result.scalars().all():
            questions_by_message_id.setdefault(question.message_id, []).append(question)

        graphics_by_message_id: dict[uuid.UUID, list[ChatMessageGraphic]] = {}
        for graphic in graphics_result.scalars().all():
            graphics_by_message_id.setdefault(graphic.message_id, []).append(graphic)

        return ChatSessionDetailRecord(
            session=session,
            messages=messages,
            clarification_questions_by_message_id=questions_by_message_id,
            graphics_by_message_id=graphics_by_message_id,
        )

    async def get_first_by_session_id(self, session_id: uuid.UUID) -> Optional[ChatMessage]:
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.send_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_recent_by_session_id(
        self,
        session_id: uuid.UUID,
        limit: int = 6,
    ) -> list[ChatMessage]:
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.send_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()
        return messages

    async def _get_session_by_id(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()
