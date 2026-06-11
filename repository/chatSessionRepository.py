import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.ChatSession import ChatSession
from utils.datetime import utc_now


class ChatSessionRepository:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def create(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str,
        chatbot_id: uuid.UUID | None = None,
    ) -> ChatSession:
        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            session_name=title[:80].strip() or "New Chat",
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_user(self, user_id: uuid.UUID) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.start_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        # Expire any cached identity-map entry so we always hit the DB
        await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id).execution_options(populate_existing=True)
        )
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_title(self, session: ChatSession, title: str) -> Optional[ChatSession]:
        session.session_name = title
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def end_session(self, session_id: uuid.UUID) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.end_at = utc_now()
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def delete(self, session: ChatSession):
        await self.db.delete(session)
        await self.db.flush()
