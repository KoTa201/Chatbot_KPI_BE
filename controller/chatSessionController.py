

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from databaseConfig import get_db
from exceptions import translate_app_errors
from service.authService import get_current_user
from service.chatSessionService import ChatSessionService
from schema.sessionSchema import SessionResponse, UpdateSessionTitleRequest, SessionDetailResponse, \
    SessionDeleteResponse
from model.User import User


class ChatSessionController:

    def __init__(self, db: AsyncSession = Depends(get_db)):
        self.service: ChatSessionService = ChatSessionService(db)

    async def handle_get_sessions(
        self,
        current_user: User = Depends(get_current_user),
    ) -> list[SessionResponse]:
        sessions = await self.service.get_sessions(user_id=current_user.id)
        return [SessionResponse.model_validate(s) for s in sessions]


    @translate_app_errors
    async def handle_get_session_detail(
        self,
        session_id: UUID,
        current_user: User = Depends(get_current_user),
    ) -> SessionDetailResponse:
        session_detail = await self.service.get_session_detail(session_id=session_id, user_id=current_user.id)
        return SessionDetailResponse.model_validate(session_detail)

    @translate_app_errors
    async def handle_delete_session(
        self,
        session_id: UUID,
        current_user: User = Depends(get_current_user),
    ) -> None:
        response = await self.service.delete_session(session_id=session_id, user_id=current_user.id)
        SessionDeleteResponse.model_validate(response)

    @translate_app_errors
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