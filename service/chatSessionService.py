from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from model import ChatSession
from repository.chatSessionRepository import ChatSessionRepository
from repository.chatMessageRepository import ChatSessionDetailRecord, ChatMessageRepository
from schema.sessionSchema import (
    SessionClarificationQuestionResponse,
    SessionGraphicItem,
    SessionMessageResponse,
)


class ChatSessionService:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.session_repo: ChatSessionRepository = ChatSessionRepository(db)
        self.message_repo: ChatMessageRepository = ChatMessageRepository(db)

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

    async def get_sessions(self, user_id: UUID) -> list:
        return await self.session_repo.get_by_user(user_id=user_id)

    async def get_session_detail(self, session_id: UUID, user_id: UUID) -> dict:
        session_detail = await self.message_repo.get_detail_by_session_id(session_id)
        checked_session_detail = self._check_session_detail_or_404(session_detail)
        self._check_user_access(checked_session_detail, user_id)

        messages = []
        for message in checked_session_detail.messages:
            questions = [
                SessionClarificationQuestionResponse(
                    id=question.clarification_question_id,
                    ambiguity_type=question.ambiguity_type,
                    question=question.clarification_question,
                    options=[option.option_text for option in question.answer_options],
                    selected_answer=question.selected_answer,
                    free_text_answer=question.free_text_answer,
                    created_at=question.created_at,
                )
                for question in checked_session_detail.clarification_questions_by_message_id.get(message.message_id, [])
                if question.ambiguity_type != "none"
            ]
            graphics = [
                SessionGraphicItem(
                    kpi_name=g.kpi_name,
                    chart_type=g.chart_type,
                    image_url=g.image_url,
                )
                for g in checked_session_detail.graphics_by_message_id.get(message.message_id, [])
            ]

            messages.append(
                SessionMessageResponse(
                    message_id=message.message_id,
                    message=message.message,
                    is_sender_chatbot=message.is_sender_chatbot,
                    send_at=message.send_at,
                    clarification_questions=questions,
                    graphics=graphics,
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
        await self.db.commit()

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
        await self.db.commit()
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

