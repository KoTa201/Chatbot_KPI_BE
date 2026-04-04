"""
controllers/auth_controller.py
Menangani logika bisnis, validasi input, dan pembentukan response
untuk semua endpoint authentication & user management.

Aturan utama:
- Registrasi user HANYA bisa dilakukan oleh user dengan role admin.
- Login terbuka untuk semua user aktif, mengembalikan access + refresh token.
- Refresh token dipakai untuk mendapatkan pasangan token baru (rotation).
- Logout merevoke refresh token aktif.
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
    RefreshRequest,         # ← schema baru
    TokenResponse,
    UpdateUserRequest,
    UserCreateRequest,
    UserResponse,
)
from service.authService import AuthService
from service.userService import UserService
# Tambahkan import schema baru
from schema.authSchema import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ResetTokenResponse,
    VerifyResetPinRequest,
)


class AuthController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuthRepository(db)
        self.svc = AuthService()
        self.user_svc = UserService()

    # ------------------------------------------------------------------ #
    #  POST /auth/login                                                    #
    # ------------------------------------------------------------------ #

    async def login(self, payload: LoginRequest) -> TokenResponse:
        """
        Verifikasi credential dan kembalikan access token + refresh token.
        Terbuka untuk semua user aktif tanpa autentikasi sebelumnya.
        """
        user = await self.svc.authenticate_user(
            identifier=payload.identifier,
            password=payload.password,
            repo=self.repo,
        )

        access_token, expires_in = self.svc.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
        )
        refresh_token, refresh_expires_in = self.svc.create_refresh_token(
            user_id=user.id,
        )

        return TokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            refresh_token=refresh_token,
            refresh_expires_in=refresh_expires_in,
            user=UserResponse.model_validate(user),
        )

    # ------------------------------------------------------------------ #
    #  POST /auth/refresh                                                  #
    # ------------------------------------------------------------------ #

    async def refresh(self, payload: RefreshRequest) -> TokenResponse:
        """
        Tukar refresh token lama dengan pasangan access + refresh token baru.
        Token lama langsung direvoke setelah dipakai (rotation).
        Raise HTTP 401 jika token tidak valid atau sudah direvoke.
        """
        new_access, access_exp, new_refresh, refresh_exp = await self.svc.rotate_tokens(
            refresh_token=payload.refresh_token,
            repo=self.repo,
        )

        return TokenResponse(
            access_token=new_access,
            expires_in=access_exp,
            refresh_token=new_refresh,
            refresh_expires_in=refresh_exp,
        )

    async def forgot_password(
        self, payload: ForgotPasswordRequest
    ) -> MessageResponse:
        # -- validasi input --
        if not payload.email or not payload.email.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'email' tidak boleh kosong.",
            )

        # -- delegasi --
        result = await self.svc.request_password_reset(email=payload.email.strip(), repo=self.repo)

        # -- mapping output --
        return MessageResponse.model_validate(result)

    async def verify_reset_pin(
        self, payload: VerifyResetPinRequest
    ) -> ResetTokenResponse:
        # -- validasi input --
        if not payload.pin.isdigit() or len(payload.pin) != 6:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PIN harus berupa 6 digit angka.",
            )

        # -- delegasi --
        result = await self.svc.verify_reset_pin(
            email=payload.email,
            pin=payload.pin,
            repo=self.repo,
        )

        # -- mapping output --
        return ResetTokenResponse.model_validate(result)

    async def reset_password(
        self, payload: ResetPasswordRequest
    ) -> MessageResponse:
        # -- validasi input --
        if len(payload.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password baru minimal 8 karakter.",
            )
        if not payload.reset_token or not payload.reset_token.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Field 'reset_token' tidak boleh kosong.",
            )

        # -- delegasi --
        result = await self.svc.reset_password(
            reset_token=payload.reset_token.strip(),
            new_password=payload.new_password,
            repo=self.repo,
        )

        # -- mapping output --
        return MessageResponse.model_validate(result)

    # ------------------------------------------------------------------ #
    #  POST /auth/logout                                                   #
    # ------------------------------------------------------------------ #

    async def logout(self, payload: RefreshRequest) -> MessageResponse:
        """
        Revoke refresh token agar tidak bisa dipakai ulang.
        Access token tetap berlaku sampai expired — client wajib menghapusnya sendiri.
        """
        await self.svc.revoke_refresh_token(
            refresh_token=payload.refresh_token,
            repo=self.repo,
        )
        return MessageResponse(message="Logout berhasil. Refresh token telah dicabut.")

    # ------------------------------------------------------------------ #
    #  POST /auth/users  (admin only)                                      #
    # ------------------------------------------------------------------ #

    async def create_user(
        self, payload: UserCreateRequest
    ) -> UserResponse:
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

    # ------------------------------------------------------------------ #
    #  GET /auth/users  (admin only)                                       #
    # ------------------------------------------------------------------ #

    async def get_all_users(
        self, limit: int, offset: int, admin: UserORM
    ) -> dict:
        # -- validasi input --
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'limit' harus antara 1 dan 100.",
            )
        if offset < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'offset' tidak boleh negatif.",
            )

        # -- delegasi --
        result = await self.user_svc.get_all_users(limit=limit, offset=offset)

        # -- validasi & mapping output --
        return {
            "total": result["total"],
            "limit": result["limit"],
            "offset": result["offset"],
            "users": [UserResponse.model_validate(u) for u in result["users"]],
        }

    # ------------------------------------------------------------------ #
    #  GET /auth/users/{user_id}  (admin only)                             #
    # ------------------------------------------------------------------ #

    async def get_user_by_id(
        self, user_id: int, admin: UserORM
    ) -> UserResponse:
        # -- validasi input --
        if user_id < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'user_id' harus berupa bilangan positif.",
            )

        # -- delegasi --
        result = await self.user_svc.get_user_by_id(user_id=user_id)

        # -- validasi & mapping output --
        return UserResponse.model_validate(result)

    # ------------------------------------------------------------------ #
    #  GET /auth/me                                                        #
    # ------------------------------------------------------------------ #

    async def get_me(self, current_user: UserORM) -> UserResponse:
        # Tidak ada input dari client, langsung mapping dari injected user
        return UserResponse.model_validate(current_user)

    # ------------------------------------------------------------------ #
    #  PATCH /auth/users/{user_id}  (admin only)                           #
    # ------------------------------------------------------------------ #

    async def update_user(
        self, user_id: int, payload: UpdateUserRequest
    ) -> UserResponse:
        # -- validasi input --
        if user_id < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'user_id' harus berupa bilangan positif.",
            )
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

    # ------------------------------------------------------------------ #
    #  POST /auth/me/change-password                                       #
    # ------------------------------------------------------------------ #

    async def change_password(
        self, payload: ChangePasswordRequest, current_user: UserORM
    ) -> MessageResponse:
        # -- validasi input --
        if not payload.old_password or not payload.new_password:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password lama dan baru wajib diisi.",
            )
        if len(payload.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Password baru minimal 8 karakter.",
            )

        # -- delegasi --
        result = await self.svc.change_password(
            payload=payload,
            current_user=current_user,
        )

        # -- validasi & mapping output --
        return MessageResponse.model_validate(result)

    # ------------------------------------------------------------------ #
    #  DELETE /auth/users/{user_id}  (admin only)                          #
    # ------------------------------------------------------------------ #

    async def delete_user(
        self, user_id: int, admin: UserORM
    ) -> MessageResponse:
        # -- validasi input --
        if user_id < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'user_id' harus berupa bilangan positif.",
            )

        # -- delegasi --
        result = await self.user_svc.delete_user(
            user_id=user_id,
            admin_id=admin.id,
        )

        # -- validasi & mapping output --
        return MessageResponse.model_validate(result)
