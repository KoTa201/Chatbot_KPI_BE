import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from model.ChatSession import ChatSession


class ChatSessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session_id: str, user_id: uuid.UUID, title: str) -> ChatSession:
        session = ChatSession(
            id=session_id,
            user_id=user_id,
            title=title[:80].strip() or "New Chat",
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_user(self, user_id: uuid.UUID) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: str) -> Optional[ChatSession]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_title(self, session_id: str, title: str) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def delete(self, session_id: str) -> bool:
        session = await self.get_by_id(session_id)
        if session is None:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True
