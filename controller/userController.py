
"""
controller/userController.py
AuthController: handles user/auth request validation and service delegation.
"""

from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model.User import RoleEnum, User
from schema.authSchema import (
    MessageResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from service.userService import UserService


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
        self, payload: UserCreateRequest, admin: User
    ) -> UserResponse:
        """[Admin] Tambah user baru."""
        # -- validasi input --
        if not payload.username or not payload.username.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'username' tidak boleh kosong.",
            )
        if not payload.email or not payload.email.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'email' tidak boleh kosong.",
            )

        # -- delegasi --
        result = await self.user_svc.create_user(payload=payload)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    async def get_all_users(
        self,
        page: int,
        limit: int,
        admin: User,
        search: str | None = None,
        role: RoleEnum | None = None,
        user_status: str | None = None,
    ) -> dict:
        """[Admin] Daftar semua user."""
        # -- validasi input --
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'limit' harus antara 1 dan 100.",
            )
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page' tidak boleh negatif dan minimal 1.",
            )
        if user_status is not None and user_status.lower() not in {"active", "inactive"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'status' harus 'active' atau 'inactive'.",
            )

        active_status_filter = None
        if user_status is not None:
            active_status_filter = user_status.lower() == "active"

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
        self, user_id: UUID, admin: User
    ) -> UserResponse:
        """[Admin] Detail user."""
        # -- delegasi --
        result = await self.user_svc.get_user_by_id(user_id=user_id)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    async def update_user(
        self, user_id: UUID, payload: UpdateUserRequest, admin: User
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
        self, user_id: UUID, admin: User
    ) -> MessageResponse:
        """[Admin] Hapus user."""
        # -- delegasi --
        result = await self.user_svc.delete_user(
            user_id=user_id,
            admin_id=admin.id,
        )

        # -- validasi & mapping output --
        return MessageResponse.model_validate(result)
