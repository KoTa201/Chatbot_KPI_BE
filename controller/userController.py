
"""
controller/userController.py
AuthController: handles user/auth request validation and service delegation.
"""

from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model.User import RoleEnum, User
from model.Base import UserStatusEnum
from schema.authSchema import (
    MessageResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from service.userService import UserService
from utils.pagination import validate_limit, validate_page


class UserController:
    """
    Controller: handles auth/user endpoints.
    Validates input, delegates to service, and returns response schema.
    """

    def __init__(self, db: AsyncSession):
        self.user_svc: UserService = UserService(
            db)  # User service for user management

    # ─── Admin user management endpoints ──────────────────────────────

    async def create_user(
        self, payload: UserCreateRequest
    ) -> UserResponse:
        """[Admin] Tambah user baru."""

        # -- delegasi --
        result = await self.user_svc.create_user(payload=payload)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    async def get_all_users(
        self,
        page: int,
        limit: int,
        search: str | None = None,
        role: RoleEnum | None = None,
        user_status: UserStatusEnum | None = None,
    ) -> dict:
        """[Admin] Daftar semua user."""
        # -- validasi input --
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )

        active_status_filter = None
        if user_status is not None:
            active_status_filter = user_status == UserStatusEnum.ACTIVE

        # -- delegasi --
        result = await self.user_svc.get_all_users(
            page=page,
            limit=limit,
            search=search,
            role=role,
            status=active_status_filter,
        )

        # -- validasi & mapping output --
        return {
            "total": result["total"],
            "page": result["page"],
            "limit": result["limit"],
            "users": [UserResponse.model_validate(u) for u in result["users"]],
        }

    async def get_user_by_id(
        self, user_id: UUID
    ) -> UserResponse:
        """[Admin] Detail user."""
        # -- delegasi --
        result = await self.user_svc.get_user_by_id(user_id=user_id)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    async def update_user(
        self, user_id: UUID, payload: UpdateUserRequest
    ) -> UserResponse:
        """[Admin] Update data user."""
        # -- validasi input --
        if not any([payload.email, payload.full_name,
                    payload.role, payload.is_active is not None]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tidak ada field yang diupdate.",
            )

        # -- delegasi --
        result = await self.user_svc.update_user(user_id=user_id, payload=payload)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    async def delete_user(
        self, user_id: UUID
    ) -> MessageResponse:
        """[Admin] Hapus user."""
        # -- delegasi --
        result = await self.user_svc.delete_user(
            user_id=user_id,
        )

        # -- validasi & mapping output --
        return MessageResponse.model_validate(result)
