from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from model.ChatMessage import ChatMessage
from model.ClarificationQuestion import ClarificationQuestion
from model.ClarificationAnswerOption import ClarificationAnswerOption


class ClarificationRepository:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def create(
        self,
        session_id: UUID,
        ambiguity_type: str,
        is_ambiguity_level1_type_llm: bool,
        clarifying_question: str,
        clarification_answer: str | None = None,
        answer_options: list[str] | None = None,
        message_id: UUID | None = None,
    ) -> ClarificationQuestion:
        question = ClarificationQuestion(
            ambiguity_type=ambiguity_type[:20] if ambiguity_type else None,
            is_ambiguity_level1_type_llm=is_ambiguity_level1_type_llm,
            clarification_question=clarifying_question,
            selected_answer=self._serialize_answer(clarification_answer),
            message_id=message_id,
        )
        self.db.add(question)
        await self.db.flush()

        if answer_options:
            for idx, option_text in enumerate(answer_options):
                self.db.add(ClarificationAnswerOption(
                    clarification_question_id=question.clarification_question_id,
                    option_text=str(option_text),
                    option_order=idx,
                ))
            await self.db.flush()
            await self.db.refresh(question, attribute_names=["answer_options"])

        return question

    async def update_with_answer(
        self,
        log_id: str,
        clarification_answer: str,
        free_text_answer: str | None = None,
    ) -> ClarificationQuestion:
        stmt = (
            select(ClarificationQuestion)
            .options(selectinload(ClarificationQuestion.answer_options))
            .where(
                ClarificationQuestion.clarification_question_id == str(log_id)
            )
        )
        result = await self.db.execute(stmt)
        question = result.scalar_one_or_none()

        if not question:
            raise ValueError(
                f"Clarification question {log_id} tidak ditemukan")

        question.selected_answer = self._serialize_answer(clarification_answer)
        question.free_text_answer = self._serialize_answer(free_text_answer)
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def get_by_session(self, session_id: UUID) -> list[ClarificationQuestion]:
        stmt = (
            select(ClarificationQuestion)
            .join(ChatMessage, ClarificationQuestion.message_id == ChatMessage.message_id)
            .options(selectinload(ClarificationQuestion.answer_options))
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_last_clarification(self, session_id: UUID) -> ClarificationQuestion | None:
        stmt = (
            select(ClarificationQuestion)
            .join(ChatMessage, ClarificationQuestion.message_id == ChatMessage.message_id)
            .options(selectinload(ClarificationQuestion.answer_options))
            .where(ChatMessage.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _serialize_answer(clarification_answer: str | None) -> str | None:
        if clarification_answer is None:
            return None
        return str(clarification_answer)[:255]
