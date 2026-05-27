from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from databaseConfig import get_db
from service.authService import get_current_user
from service.chatSessionService import ChatSessionService
from schema.sessionSchema import SessionResponse, UpdateSessionTitleRequest, SessionDetailResponse
from model.User import User


class ChatSessionController:

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.service = ChatSessionService(db)

    async def handle_get_sessions(
        self,
        current_user: User = Depends(get_current_user),
    ) -> list[SessionResponse]:
        sessions = await self.service.get_sessions(user_id=str(current_user.id))
        return [SessionResponse.model_validate(s) for s in sessions]


    async def handle_get_session_detail(
        self,
        session_id: UUID,
        current_user: User = Depends(get_current_user),
    ) -> SessionDetailResponse:
        service = ChatSessionService(self.db)
        return await service.get_session_detail(session_id=session_id, user_id=current_user.id)

    async def handle_delete_session(
        self,
        session_id: UUID,
        current_user: User = Depends(get_current_user),
    ) -> None:
        await self.service.delete_session(session_id=session_id, user_id=current_user.id)

    async def handle_update_session_title(
        self,
        session_id: UUID,
        request: UpdateSessionTitleRequest,
        current_user: User = Depends(get_current_user),
    ) -> SessionResponse:
        updated = await self.service.update_session_title(
            session_id=session_id,
            user_id=current_user.id,
            title=request.title,
        )
        return SessionResponse.model_validate(updated)