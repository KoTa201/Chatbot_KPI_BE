import logging
from uuid import UUID

from fastapi import HTTPException, status
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from schema.authSchema import (
    MessageResponse,
    UpdateUserRequest,
    UserCreateRequest,
)
from repository.userRepository import UserRepository
from model.User import RoleEnum, User
from service.emailService import EmailService
from service.authService import AuthService
from databaseConfig import AsyncSessionLocal


logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db: AsyncSession):
        self.repo: UserRepository = UserRepository(db)
        self.auth_service: AuthService = AuthService(repo=self.repo)
        self.email_service: EmailService = EmailService()

    async def create_user(self, payload: UserCreateRequest) -> User:
        if await self.repo.email_exists(payload.email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Email '{payload.email}' sudah digunakan oleh user lain.",
            )
            
        user = User(
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
            hashed_password=self.auth_service.hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        user = await self.repo.create_user(user)

        try:
            self.email_service.send_credentials_info_background(
                to_email=user.email,
                full_name=user.full_name or user.username,
                username=user.username,
                password=payload.password,
                role=user.role,
            )
        except Exception as exc:
            logger.warning(
                "Gagal menjadwalkan email kredensial untuk user '%s': %s",
                user.username,
                exc,
            )

        return user

    async def get_all_users(
        self,
        page: int,
        limit: int,
        search: str | None = None,
        role: RoleEnum | None = None,
        status: bool | None = None,
    ) -> dict:
        async with AsyncSessionLocal() as second_session:
            count_repo = UserRepository(second_session)
            users, total = await asyncio.gather(
                self.repo.get_all_users(
                    page=page, limit=limit, search=search, role=role, status=status
                ),
                count_repo.count_all_users(
                    search=search, role=role, status=status),
            )

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "users": users,  # List[User], formatting dilakukan di controller
        }

    async def get_user_by_id(self, user_id: UUID) -> User:
        return await self._get_user_or_404(user_id)

    async def update_user(self, user_id: UUID, payload: UpdateUserRequest) -> User:
        user = await self._get_user_or_404(user_id)

        if payload.email and payload.email != user.email:
            if await self.repo.email_exists(payload.email):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Email '{payload.email}' sudah digunakan oleh user lain.",
                )

        update_data = payload.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        return await self.repo.save(user)

    async def delete_user(self, user_id: UUID) -> dict:
        user = await self._get_user_or_404(user_id)

        if user.role == RoleEnum.admin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin tidak dapat menghapus dirinya sendiri.",
            )

        await self.repo.delete_user(user)
        return {"message": f"User id={user_id} berhasil dihapus permanen.", "success": True}

    async def _get_user_or_404(self, user_id: UUID) -> User:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User dengan ID {user_id} tidak ditemukan.",
            )
        return user
