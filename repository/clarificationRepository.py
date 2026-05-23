import json
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.ClarificationQuestion import ClarificationQuestion


class ClarificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        session_id: UUID,
        ambiguity_type: str,
        is_ambiguity_level1_type_llm: bool,
        clarifying_question: str,
        clarification_answer: str | None = None,
        answer_options: list[str] | None = None,
        message_id: str | None = None,
    ) -> ClarificationQuestion:
        question = ClarificationQuestion(
            ambiguity_type=ambiguity_type[:20] if ambiguity_type else None,
            is_ambiguity_level1_type_llm=is_ambiguity_level1_type_llm,
            clarification_question=clarifying_question,
            answer_options=self._serialize_options(answer_options),
            selected_answer=self._serialize_answer(clarification_answer),
            message_id=message_id,
            session_id=session_id,
        )
        self.db.add(question)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def update_with_answer(
        self,
        log_id: str,
        clarification_answer: str,
        disambiguated_query: str,
        free_text_answer: str | None = None,
    ) -> ClarificationQuestion:
        stmt = select(ClarificationQuestion).where(
            ClarificationQuestion.clarification_question_id == str(log_id)
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
        await self.db.commit()
        await self.db.refresh(question)
        return question

    async def get_by_session(self, session_id: UUID) -> list[ClarificationQuestion]:
        stmt = (
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_last_clarification(self, session_id: UUID) -> ClarificationQuestion | None:
        stmt = (
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_feedback(
        self,
        log_id: UUID,
        user_feedback: bool,
        needed_correction: bool | None = None,
    ) -> None:
        return None

    async def get_clarify_decisions_count(self, session_id: UUID) -> int:
        return 0

    async def delete_by_session(self, session_id: UUID) -> int:
        return 0

    @staticmethod
    def _serialize_options(answer_options: list[str] | None) -> str | None:
        if not answer_options:
            return None
        return json.dumps(answer_options, ensure_ascii=False)[:255]

    @staticmethod
    def _serialize_answer(clarification_answer: str | None) -> str | None:
        if clarification_answer is None:
            return None
        return str(clarification_answer)[:255]
