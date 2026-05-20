from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from repository.chatSessionRepository import ChatSessionRepository


class ChatSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = ChatSessionRepository(db)

    async def create_session_if_missing(
        self,
        session_id: UUID,
        user_id: str,
        first_message: str,
    ) -> None:
        existing = await self.session_repo.get_by_id(session_id)
        if existing is None:
            await self.session_repo.create(
                session_id=session_id,
                user_id=UUID(user_id),
                title=first_message[:80].strip() or "New Chat",
            )

    async def get_sessions(self, user_id: str) -> list:
        return await self.session_repo.get_by_user(user_id=UUID(user_id))

    async def delete_session(self, session_id: UUID, user_id: str) -> None:
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.session_repo.delete(session_id)
        await self.db.flush()

    async def update_session_title(
        self,
        session_id: UUID,
        user_id: str,
        title: str,
    ):
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        updated = await self.session_repo.update_title(session_id, title)
        await self.db.flush()
        return updated
