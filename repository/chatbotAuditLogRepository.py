import uuid
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from model.ChatbotAuditLog import ChatbotAuditLog


class AuditLogRepository:
    """Menangani semua interaksi database untuk ChatbotAuditLog."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> ChatbotAuditLog:
        log = ChatbotAuditLog(**data)
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> list[ChatbotAuditLog]:
        result = await self.db.execute(
            select(ChatbotAuditLog)
            .where(ChatbotAuditLog.user_id == user_id)
            .order_by(ChatbotAuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_session(self, session_id: str) -> list[ChatbotAuditLog]:
        result = await self.db.execute(
            select(ChatbotAuditLog)
            .where(ChatbotAuditLog.session_id == session_id)
            .order_by(ChatbotAuditLog.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_failed_wireguard(
        self, skip: int = 0, limit: int = 100
    ) -> list[ChatbotAuditLog]:
        result = await self.db.execute(
            select(ChatbotAuditLog)
            .where(ChatbotAuditLog.wireguard_status == "FAIL")
            .order_by(ChatbotAuditLog.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, log_id: uuid.UUID) -> Optional[ChatbotAuditLog]:
        result = await self.db.execute(
            select(ChatbotAuditLog).where(ChatbotAuditLog.id == log_id)
        )
        return result.scalar_one_or_none()

    async def delete_by_session(self, session_id: str) -> int:
        result = await self.db.execute(
            delete(ChatbotAuditLog).where(ChatbotAuditLog.session_id == session_id)
        )
        await self.db.flush()
        return result.rowcount
