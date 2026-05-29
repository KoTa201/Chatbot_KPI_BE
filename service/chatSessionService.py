

import json
from types import CoroutineType
from typing import List, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from model import ChatSession
from repository.chatSessionRepository import ChatSessionRepository, ChatSessionDetailRecord
from schema.sessionSchema import (
    SessionClarificationQuestionResponse,
    SessionDetailResponse,
    SessionMessageResponse,
)


class ChatSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = ChatSessionRepository(db)

    async def create_session_if_missing(
        self,
        session_id: UUID,
        user_id: UUID,
        first_message: str,
        chatbot_id: UUID | None = None,
    ) -> None:
        existing = await self.session_repo.get_by_id(session_id)
        if existing is None:
            await self.session_repo.create(
                session_id=session_id,
                user_id=user_id,
                title=first_message[:80].strip() or "New Chat",
                chatbot_id=chatbot_id,
            )

    async def create_user_message(self, session_id: UUID, message: str):
        return await self.session_repo.create_message(
            session_id=session_id,
            message=message,
            is_sender_chatbot=False,
        )

    async def create_chatbot_message(self, session_id: UUID, message: str):
        return await self.session_repo.create_message(
            session_id=session_id,
            message=message,
            is_sender_chatbot=True,
        )

    async def get_sessions(self, user_id: UUID) -> list:
        return await self.session_repo.get_by_user(user_id=user_id)

    async def get_session_detail(self, session_id: UUID, user_id: UUID) -> dict:
        session_detail = await self.session_repo.get_detail_by_id(session_id)
        checked_session_detail = self._check_session_detail_or_404(session_detail)
        self._check_user_access(checked_session_detail, user_id)

        messages = []
        for message in checked_session_detail.messages:
            questions = [
                SessionClarificationQuestionResponse(
                    id=question.clarification_question_id,
                    ambiguity_type=question.ambiguity_type,
                    question=question.clarification_question,
                    options=self._parse_options(question.answer_options),
                    selected_answer=question.selected_answer,
                    free_text_answer=question.free_text_answer,
                    created_at=question.created_at,
                )
                for question in checked_session_detail.clarification_questions_by_message_id.get(message.message_id, [])
            ]
            messages.append(
                SessionMessageResponse(
                    message_id=message.message_id,
                    message=message.message,
                    is_sender_chatbot=message.is_sender_chatbot,
                    send_at=message.send_at,
                    clarification_questions=questions,
                )
            )

        return {
            "id": checked_session_detail.session.id,
            "title": checked_session_detail.session.title,
            "created_at": checked_session_detail.session.created_at,
            "updated_at": checked_session_detail.session.updated_at,
            "messages": messages,
        }

    async def delete_session(self, session_id: UUID, user_id: UUID) -> dict:
        session = await self.session_repo.get_by_id(session_id)
        checked_session = self._check_session_or_404(session)
        self._check_user_access(checked_session, user_id)
        await self.session_repo.delete(checked_session)
        await self.db.flush()

        return {
            "message": "Session berhasil dihapus.",
            "success": True,
            "status_code": status.HTTP_200_OK,
        }

    async def update_session_title(
        self,
        session_id: UUID,
        user_id: UUID,
        title: str,
    ):
        session = await self.session_repo.get_by_id(session_id)
        checked_session = self._check_session_or_404(session)
        self._check_user_access(checked_session, user_id)
        updated = await self.session_repo.update_title(checked_session, title)
        await self.db.flush()
        return updated

    @staticmethod
    def _check_session_or_404(
            session: ChatSession | None,
    ) -> ChatSession :  # ← narrowed return type
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        return session  # ← return it

    @staticmethod
    def _check_session_detail_or_404(
            session: ChatSessionDetailRecord | None,
    ) -> ChatSessionDetailRecord :  # ← narrowed return type
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        return session  # ← return it

    @staticmethod
    def _check_user_access(session: ChatSession | ChatSessionDetailRecord, user_id: UUID):
        session_user_id = (
            session.user_id
            if isinstance(session, ChatSession)
            else session.session.user_id
        )
        if str(session_user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )

    @staticmethod
    def _parse_options(answer_options: str | None) -> list[str]:
        if not answer_options:
            return []
        try:
            options = json.loads(answer_options)
        except json.JSONDecodeError:
            return []
        if not isinstance(options, list):
            return []
        return [str(option) for option in options]
