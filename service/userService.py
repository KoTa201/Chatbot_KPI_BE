
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
from service.authService import AuthService, require_admin


class UserService:
    def __init__(self, db: AsyncSession):
        self.repo = AuthRepository(db)
        self.auth_service = AuthService()

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

        new_user = UserORM(
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=self.auth_service.hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        created = await self.repo.create_user(new_user)
        return UserResponse.model_validate(created)

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
        user = await self.auth_service._get_user_or_404(user_id)
        return UserResponse.model_validate(user)

    async def update_user(
        self, user_id: UUID, payload: UpdateUserRequest
    ) -> UserResponse:
        user = await self.auth_service._get_user_or_404(user_id)

        if payload.email and payload.email != user.email:
            if await self.repo.email_exists(payload.email):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Email '{payload.email}' sudah digunakan oleh user lain.",
                )
            user.email = payload.email

        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.role is not None:
            user.role = payload.role
        if payload.is_active is not None:
            user.is_active = payload.is_active

        updated = await self.repo.save(user)
        return UserResponse.model_validate(updated)

    async def delete_user(self, user_id: UUID, admin_id: UUID) -> MessageResponse:
        if user_id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin tidak dapat menghapus akun sendiri.",
            )
        user = await self.auth_service._get_user_or_404(user_id)
        await self.repo.delete_user(user)
        return MessageResponse(message=f"User '{user.username}' berhasil dihapus.")
