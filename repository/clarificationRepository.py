"""
repository/clarificationRepository.py
Data access layer untuk clarification logs.
"""

from uuid import UUID
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.ClarificationLog import ClarificationLogORM
from schema.clarificationSchema import ClarificationLogEntry


class ClarificationRepository:
    """Repository untuk CRUD operations pada clarification logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        session_id: str,
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
    ) -> ClarificationLogORM:
        """Membuat log entry baru untuk clarification."""
        log = ClarificationLogORM(
            session_id=session_id,
            user_id=user_id,
            user_role=user_role,
            original_query=original_query,
            ambiguity_score=ambiguity_score,
            ambiguity_type=ambiguity_type,
            decision=decision,
            decision_source=decision_source,
            clarifying_question=clarifying_question,
            clarification_answer=clarification_answer,
            disambiguated_query=disambiguated_query,
        )
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def update_with_answer(
        self,
        log_id: UUID,
        clarification_answer: str,
        disambiguated_query: str,
    ) -> ClarificationLogORM:
        """Update log dengan jawaban klarifikasi dan query yang sudah disambiguasi."""
        stmt = select(ClarificationLogORM).where(ClarificationLogORM.id == log_id)
        result = await self.db.execute(stmt)
        log = result.scalar_one_or_none()
        
        if not log:
            raise ValueError(f"Log {log_id} tidak ditemukan")
        
        log.clarification_answer = clarification_answer
        log.disambiguated_query = disambiguated_query
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def update_feedback(
        self,
        log_id: UUID,
        user_feedback: bool,
        needed_correction: bool | None = None,
    ) -> ClarificationLogORM:
        """Update feedback pengguna untuk log."""
        stmt = select(ClarificationLogORM).where(ClarificationLogORM.id == log_id)
        result = await self.db.execute(stmt)
        log = result.scalar_one_or_none()
        
        if not log:
            raise ValueError(f"Log {log_id} tidak ditemukan")
        
        log.user_feedback = user_feedback
        if needed_correction is not None:
            log.needed_correction = needed_correction
        
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        return log

    async def get_by_session(self, session_id: str) -> list[ClarificationLogEntry]:
        """Mendapatkan semua log untuk satu session."""
        stmt = (
            select(ClarificationLogORM)
            .where(ClarificationLogORM.session_id == session_id)
            .order_by(desc(ClarificationLogORM.created_at))
        )
        result = await self.db.execute(stmt)
        logs = result.scalars().all()
        return [ClarificationLogEntry.from_orm(log) for log in logs]

    async def get_by_user(
        self,
        user_id: UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[ClarificationLogEntry], int]:
        """Mendapatkan log clarification untuk satu user dengan pagination."""
        # Get total count
        count_stmt = select(ClarificationLogORM).where(ClarificationLogORM.user_id == user_id)
        count_result = await self.db.execute(count_stmt)
        total = len(count_result.scalars().all())

        # Get paginated results
        stmt = (
            select(ClarificationLogORM)
            .where(ClarificationLogORM.user_id == user_id)
            .order_by(desc(ClarificationLogORM.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        logs = result.scalars().all()
        return [ClarificationLogEntry.from_orm(log) for log in logs], total

    async def get_clarify_decisions_count(self, session_id: str) -> int:
        """Menghitung berapa kali keputusan 'clarify' di satu session."""
        stmt = select(ClarificationLogORM).where(
            (ClarificationLogORM.session_id == session_id)
            & (ClarificationLogORM.decision == "clarify")
        )
        result = await self.db.execute(stmt)
        return len(result.scalars().all())

    async def get_last_clarification(self, session_id: str) -> ClarificationLogORM | None:
        """Mendapatkan clarification terakhir di satu session."""
        stmt = (
            select(ClarificationLogORM)
            .where(ClarificationLogORM.session_id == session_id)
            .order_by(desc(ClarificationLogORM.created_at))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
