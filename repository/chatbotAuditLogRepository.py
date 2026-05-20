import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> dict:
        return data

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Any]:
        return []

    async def get_by_session(self, session_id: str) -> list[Any]:
        return []

    async def get_failed_wireguard(
        self, skip: int = 0, limit: int = 100
    ) -> list[Any]:
        return []

    async def get_by_id(self, log_id: uuid.UUID) -> None:
        return None

    async def delete_by_session(self, session_id: str) -> int:
        return 0
