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
        user_id: UUID,
        user_role: str,
        original_query: str,
        ambiguity_score: float,
        ambiguity_type: str,
        decision: str,
        decision_source: str,
        clarifying_question: str | None = None,
        clarification_answer: str | None = None,
        disambiguated_query: str | None = None,
        answer_options: list[str] | None = None,
        message_id: str | None = None,
    ) -> ClarificationQuestion:
        question = ClarificationQuestion(
            ambiguous_phrase=original_query[:255],
            ambiguity_type=ambiguity_type[:20] if ambiguity_type else None,
            clarification_question=clarifying_question or original_query[:255],
            answer_options=json.dumps(answer_options)[:255] if answer_options else None,
            user_answer=self._parse_user_answer(clarification_answer),
            message_id=message_id,
        )
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def update_with_answer(
        self,
        log_id: str,
        clarification_answer: str,
        disambiguated_query: str,
    ) -> ClarificationQuestion:
        stmt = select(ClarificationQuestion).where(
            ClarificationQuestion.clarification_question_id == str(log_id)
        )
        result = await self.db.execute(stmt)
        question = result.scalar_one_or_none()

        if not question:
            raise ValueError(f"Clarification question {log_id} tidak ditemukan")

        question.user_answer = self._parse_user_answer(clarification_answer)
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def get_by_session(self, session_id: UUID) -> list[ClarificationQuestion]:
        stmt = (
            select(ClarificationQuestion)
            .order_by(desc(ClarificationQuestion.created_at))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_last_clarification(self, session_id: UUID) -> ClarificationQuestion | None:
        stmt = (
            select(ClarificationQuestion)
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
    def _parse_user_answer(clarification_answer: str | None) -> int | None:
        if clarification_answer is None:
            return None
        try:
            return int(clarification_answer)
        except ValueError:
            return None
