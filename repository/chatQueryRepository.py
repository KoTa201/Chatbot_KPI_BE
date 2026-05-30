from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ChatQueryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def execute_read_query(self, sql: str) -> tuple[list[dict], int]:
        result = await self.db.execute(text(sql))
        rows = result.mappings().all()
        data = [dict(row) for row in rows]
        return data, len(data)
