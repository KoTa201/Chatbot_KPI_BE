"""
controllers/auth_controller.py
Menangani logika bisnis, validasi input, dan pembentukan response
untuk semua endpoint authentication & user management.

Aturan utama:
- Registrasi user HANYA bisa dilakukan oleh user dengan role admin.
- Login terbuka untuk semua user aktif.
- Ganti password hanya untuk diri sendiri.
- Update & delete user hanya bisa dilakukan oleh admin.
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model.User import UserORM
from repository.userRepository import AuthRepository
from schema.authSchema import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from service.userService import AuthService


class AuthController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)
        self.svc = AuthService()

    # ------------------------------------------------------------------ #
    #  POST /auth/login                                                    #
    # ------------------------------------------------------------------ #

    async def login(self, payload: LoginRequest) -> TokenResponse:
        """
        Verifikasi credential dan kembalikan JWT access token.
        Terbuka untuk semua user aktif tanpa autentikasi sebelumnya.
        """
        user = await self.svc.authenticate_user(
            identifier=payload.identifier,
            password=payload.password,
            repo=self.repo,
        )

        token, expires_in = self.svc.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
        )

        return TokenResponse(
            access_token=token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )

    # ------------------------------------------------------------------ #
    #  POST /auth/users  (admin only)                                      #
    # ------------------------------------------------------------------ #

    async def create_user(
        self,
        payload: UserCreateRequest,
        admin: UserORM,
    ) -> UserResponse:
        """
        Tambah user baru. Hanya bisa dipanggil oleh admin.
        Validasi duplikasi username & email sebelum insert.
        """
        # Validasi duplikasi
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
            hashed_password=self.svc.hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        created = await self.repo.create_user(new_user)
        return UserResponse.model_validate(created)

    # ------------------------------------------------------------------ #
    #  GET /auth/users  (admin only)                                       #
    # ------------------------------------------------------------------ #

    async def get_all_users(
        self,
        limit: int,
        offset: int,
        admin: UserORM,
    ) -> dict:
        """Ambil daftar semua user dengan pagination. Hanya untuk admin."""
        users = await self.repo.get_all_users(limit=limit, offset=offset)
        total = await self.repo.count_all_users()
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "users": [UserResponse.model_validate(u) for u in users],
        }

    # ------------------------------------------------------------------ #
    #  GET /auth/users/{user_id}  (admin only)                             #
    # ------------------------------------------------------------------ #

    async def get_user_by_id(self, user_id: int, admin: UserORM) -> UserResponse:
        """Ambil detail satu user berdasarkan ID. Hanya untuk admin."""
        user = await self._get_user_or_404(user_id)
        return UserResponse.model_validate(user)

    # ------------------------------------------------------------------ #
    #  GET /auth/me                                                        #
    # ------------------------------------------------------------------ #

    async def get_me(self, current_user: UserORM) -> UserResponse:
        """Kembalikan profil user yang sedang login."""
        return UserResponse.model_validate(current_user)

    # ------------------------------------------------------------------ #
    #  PATCH /auth/users/{user_id}  (admin only)                           #
    # ------------------------------------------------------------------ #

    async def update_user(
        self,
        user_id: int,
        payload: UpdateUserRequest,
        admin: UserORM,
    ) -> UserResponse:
        """
        Update data user (full_name, email, role, is_active).
        Hanya admin yang dapat mengakses. Validasi duplikasi email jika diubah.
        """
        user = await self._get_user_or_404(user_id)

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

    # ------------------------------------------------------------------ #
    #  POST /auth/me/change-password                                       #
    # ------------------------------------------------------------------ #

    async def change_password(
        self,
        payload: ChangePasswordRequest,
        current_user: UserORM,
    ) -> MessageResponse:
        """
        Ganti password diri sendiri.
        Verifikasi old_password sebelum menyimpan password baru.
        """
        if not self.svc.verify_password(payload.old_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password lama tidak sesuai.",
            )
        if payload.old_password == payload.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password baru tidak boleh sama dengan password lama.",
            )

        current_user.hashed_password = self.svc.hash_password(
            payload.new_password)
        await self.repo.save(current_user)
        return MessageResponse(message="Password berhasil diubah.")

    # ------------------------------------------------------------------ #
    #  DELETE /auth/users/{user_id}  (admin only)                          #
    # ------------------------------------------------------------------ #

    async def delete_user(self, user_id: int, admin: UserORM) -> MessageResponse:
        """
        Hard-delete user berdasarkan ID. Hanya untuk admin.
        Admin tidak dapat menghapus akunnya sendiri.
        """
        if user_id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin tidak dapat menghapus akun sendiri.",
            )

        user = await self._get_user_or_404(user_id)
        await self.repo.delete_user(user)
        return MessageResponse(message=f"User '{user.username}' berhasil dihapus.")

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _get_user_or_404(self, user_id: int) -> UserORM:
        """Ambil user by ID, raise HTTP 404 jika tidak ditemukan."""
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User dengan ID {user_id} tidak ditemukan.",
            )
        return user
