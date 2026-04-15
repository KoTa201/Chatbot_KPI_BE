
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from schema.authSchema import (
    MessageResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from repository.userRepository import AuthRepository
from model.User import UserORM
from service.emailService import EmailService
from service.authService import AuthService, require_admin


logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession):
        self.repo = AuthRepository(db)
        self.auth_service = AuthService()
        self.email_service = EmailService()
        # Akan di-set di Depends(require_admin) pada router
        self.user: UserORM = None

        # ------------------------------------------------------------------ #
    #  User management                                                     #
    # ------------------------------------------------------------------ #

    async def create_user(self, payload: UserCreateRequest) -> UserResponse:
        if await self.repo.username_exists(payload.username):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{payload.username}' sudah digunakan.",
            )
        if await self.repo.email_exists(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.email}' sudah terdaftar.",
            )

        self.user = UserORM(
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=self.auth_service.hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        self.user = await self.repo.create_user(self.user)

        try:
            self.email_service.send_credentials_info_background(
                to_email=self.user.email,
                full_name=self.user.full_name or self.user.username,
                username=self.user.username,
                password=payload.password,
                role=self.user.role,
            )
        except Exception as exc:
            logger.warning(
                "Gagal menjadwalkan email kredensial untuk user '%s': %s",
                self.user.username,
                exc,
            )

        return UserResponse.model_validate(self.user)

    async def get_all_users(self, limit: int, offset: int) -> dict:
        users = await self.repo.get_all_users(limit=limit, offset=offset)
        total = await self.repo.count_all_users()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "users": [UserResponse.model_validate(u) for u in users],
        }

    async def get_user_by_id(self, user_id: UUID) -> UserResponse:
        self.user = await self.auth_service._get_user_or_404(user_id)
        return UserResponse.model_validate(self.user)

    async def update_user(
        self, user_id: UUID, payload: UpdateUserRequest
    ) -> UserResponse:
        self.user = await self.auth_service._get_user_or_404(user_id)

        if payload.email and payload.email != self.user.email:
            if await self.repo.email_exists(payload.email):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Email '{payload.email}' sudah digunakan oleh user lain.",
                )
            self.user.email = payload.email

        if payload.full_name is not None:
            self.user.full_name = payload.full_name
        if payload.role is not None:
            self.user.role = payload.role
        if payload.is_active is not None:
            self.user.is_active = payload.is_active

        self.user = await self.repo.save(self.user)
        return UserResponse.model_validate(self.user)

    async def delete_user(self, user_id: UUID, admin_id: UUID) -> MessageResponse:
        if user_id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin tidak dapat menghapus akun sendiri.",
            )
        self.user = await self.auth_service._get_user_or_404(user_id)
        await self.repo.delete_user(self.user)
        return MessageResponse(message=f"User '{self.user.username}' berhasil dihapus.")
