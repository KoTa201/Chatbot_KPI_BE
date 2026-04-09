"""
services/auth_service.py
Logika bisnis authentication:
- Password hashing & verification (bcrypt langsung, tanpa passlib)
- JWT access token — generate & decode
- Refresh token — generate, decode, rotate & revoke
- Dependency FastAPI untuk mendapatkan current user dari token
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import random
import secrets
from datetime import datetime, timedelta, timezone

from model.PasswordReset import PasswordResetORM
from schema.authSchema import (
    ForgotPasswordRequest,   # sudah ada di import, tambahkan yang baru
    ResetPasswordRequest,
    ResetTokenResponse,
    VerifyResetPinRequest,
)
from service.emailService import EmailService

from config import settings
from databaseConfig import get_db
from model.User import RoleEnum, UserORM
from repository.userRepository import AuthRepository
from schema.authSchema import (
    ChangePasswordRequest,
    MessageResponse
)

# ------------------------------------------------------------------ #
#  Konfigurasi                                                         #
# ------------------------------------------------------------------ #

ALGORITHM = "HS256"
TOKEN_TYPE = "bearer"
REFRESH_TOKEN_TYPE = "refresh"
RESET_TOKEN_TYPE = "reset"
PIN_EXPIRE_MINUTES = 15
RESET_TOKEN_EXPIRE_MINUTES = 10

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthService:

    def __init__(self):
        self.repo = AuthRepository(Depends(get_db))
        self.secret_key = settings.SECRET_KEY
        self.refresh_secret_key = settings.REFRESH_SECRET_KEY
        self.reset_secret_key = settings.RESET_SECRET_KEY
        self.access_token_expire_minutes = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days = settings.REFRESH_TOKEN_EXPIRE_DAYS

    async def _get_user_or_404(self, user_id: UUID) -> UserORM:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User dengan ID {user_id} tidak ditemukan.",
            )
        return user

    # ------------------------------------------------------------------ #
    #  Password                                                            #
    # ------------------------------------------------------------------ #

    def hash_password(self, plain_password: str) -> str:
        password_bytes = plain_password.encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        return hashed.decode("utf-8")

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)

    # ------------------------------------------------------------------ #
    #  JWT — Access Token                                                  #
    # ------------------------------------------------------------------ #

    def create_access_token(
        self,
        user_id: int,
        username: str,
        role: RoleEnum,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, int]:
        """
        Buat JWT access token berumur pendek.

        Returns:
            (token_string, expires_in_seconds)
        """
        expire_seconds = (
            int(expires_delta.total_seconds())
            if expires_delta
            else self.access_token_expire_minutes * 60
        )
        expire_at = datetime.now(timezone.utc) + \
            timedelta(seconds=expire_seconds)

        payload = {
            "sub": str(user_id),
            "username": username,
            "role": role.value,
            "type": TOKEN_TYPE,          # ← tandai sebagai access token
            "exp": expire_at,
        }
        token = jwt.encode(payload, self.secret_key, algorithm=ALGORITHM)
        return token, expire_seconds

    def decode_access_token(self, token: str) -> dict:
        """
        Decode dan validasi JWT access token.
        Raise HTTP 401 jika token tidak valid, kadaluarsa, atau bukan access token.
        """
        try:
            payload = jwt.decode(token, self.secret_key,
                                 algorithms=[ALGORITHM])
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid atau sudah kadaluarsa.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Tolak jika ternyata refresh token dikirim ke endpoint biasa
        if payload.get("type") != TOKEN_TYPE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload

    # ------------------------------------------------------------------ #
    #  JWT — Refresh Token                                                 #
    # ------------------------------------------------------------------ #

    def create_refresh_token(
        self,
        user_id: int,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, int]:
        """
        Buat JWT refresh token berumur panjang.
        Refresh token hanya menyimpan `sub` dan `type` — tanpa data sensitif
        seperti role, agar payload sekecil mungkin.

        Returns:
            (token_string, expires_in_seconds)
        """
        expire_seconds = (
            int(expires_delta.total_seconds())
            if expires_delta
            else self.refresh_token_expire_days * 86_400
        )
        expire_at = datetime.now(timezone.utc) + \
            timedelta(seconds=expire_seconds)

        payload = {
            "sub": str(user_id),
            "type": REFRESH_TOKEN_TYPE,  # ← tandai sebagai refresh token
            "exp": expire_at,
            "jti": str(uuid.uuid4()),
        }
        # Gunakan secret terpisah agar refresh token tidak bisa
        # dipalsukan dengan secret yang bocor dari access token.
        token = jwt.encode(
            payload, self.refresh_secret_key, algorithm=ALGORITHM
        )
        return token, expire_seconds

    def decode_refresh_token(self, token: str) -> dict:
        """
        Decode dan validasi JWT refresh token.
        Raise HTTP 401 jika token tidak valid, kadaluarsa, atau bukan refresh token.
        """
        try:
            payload = jwt.decode(
                token, self.refresh_secret_key, algorithms=[ALGORITHM]
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token tidak valid atau sudah kadaluarsa.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("type") != REFRESH_TOKEN_TYPE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan refresh token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload

    # ------------------------------------------------------------------ #
    #  Token Rotation                                                      #
    # ------------------------------------------------------------------ #

    async def rotate_tokens(
        self,
        refresh_token: str,
        repo: AuthRepository,
    ) -> tuple[str, int, str, int]:
        """
        Implementasi Refresh Token Rotation:
        1. Decode & validasi refresh token lama.
        2. Periksa apakah token sudah direvoke (ada di denylist repo).
        3. Revoke token lama (simpan ke denylist).
        4. Ambil data user terbaru dari DB.
        5. Terbitkan pasangan access + refresh token baru.

        Returns:
            (new_access_token, access_exp, new_refresh_token, refresh_exp)

        Raises:
            HTTP 401 — token tidak valid / sudah direvoke.
            HTTP 403 — akun tidak aktif.
        """
        payload = self.decode_refresh_token(refresh_token)

        user_id = UUID(payload["sub"])

        # Cek denylist — deteksi token reuse
        if await repo.is_token_revoked(refresh_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token sudah digunakan atau dicabut. Silakan login ulang.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Revoke token lama sebelum menerbitkan yang baru
        await repo.revoke_token(refresh_token)

        # Ambil user terbaru (role bisa berubah sejak token dibuat)
        user = await repo.get_by_id(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User tidak ditemukan.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun tidak aktif.",
            )

        new_access, access_exp = self.create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
        )
        new_refresh, refresh_exp = self.create_refresh_token(user_id=user.id)

        return new_access, access_exp, new_refresh, refresh_exp

    async def revoke_refresh_token(
        self,
        refresh_token: str,
        repo: AuthRepository,
    ) -> None:
        """
        Revoke refresh token secara eksplisit (dipakai saat logout).
        Token yang sudah ada di denylist diabaikan tanpa error.
        """
        # Tetap decode untuk validasi signature & expiry
        self.decode_refresh_token(refresh_token)
        await repo.revoke_token(refresh_token)

    # ------------------------------------------------------------------ #
    #  User validation                                                     #
    # ------------------------------------------------------------------ #

    async def authenticate_user(
        self,
        identifier: str,
        password: str,
        repo: AuthRepository,
    ) -> UserORM:
        """
        Verifikasi credential. Field `identifier` bisa berupa username atau email.
        Raise HTTP 401 jika credential salah atau user tidak ditemukan.
        Raise HTTP 403 jika akun tidak aktif.
        """
        user = await repo.get_by_username_or_email(identifier)

        if not user or not self.verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Username/email atau password salah.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Akun tidak aktif. Hubungi administrator.",
            )
        return user

    async def change_password(
        self, payload: ChangePasswordRequest, current_user: UserORM
    ) -> MessageResponse:
        if not self.verify_password(payload.old_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password lama tidak sesuai.",
            )
        if payload.old_password == payload.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password baru tidak boleh sama dengan password lama.",
            )

        current_user.hashed_password = self.hash_password(payload.new_password)
        await self.repo.save(current_user)
        return MessageResponse(message="Password berhasil diubah.")

    async def request_password_reset(self, email: str, repo: AuthRepository) -> MessageResponse:
        """
        Buat PIN 6 digit, simpan hash-nya ke DB, kirim ke email user.
        Selalu kembalikan pesan sukses generik — jangan bocorkan
        apakah email terdaftar atau tidak (cegah user enumeration).
        """
        _GENERIC_OK = MessageResponse(
            message="Jika email terdaftar, kode reset akan dikirim dalam beberapa saat."
        )

        user = await repo.get_by_email(email)
        if not user or not user.is_active:
            return _GENERIC_OK   # ← sengaja tidak raise 404

        pin = f"{random.SystemRandom().randint(0, 999_999):06d}"
        pin_hash = self.hash_password(pin)   # bcrypt — sama seperti password

        expires_at = datetime.now(timezone.utc) + \
            timedelta(minutes=PIN_EXPIRE_MINUTES)
        record = PasswordResetORM(
            user_id=user.id,
            pin_hash=pin_hash,
            expires_at=expires_at,
        )
        await repo.create_reset_pin(record)

        EmailService().send_reset_pin(
            to_email=user.email,
            full_name=user.full_name or user.username,
            pin=pin,
        )
        return _GENERIC_OK

    async def verify_reset_pin(self, email: str, pin: str, repo: AuthRepository) -> ResetTokenResponse:
        """
        Verifikasi PIN. Jika valid, kembalikan reset_token (JWT pendek sekali pakai).
        PIN langsung ditandai used_at agar tidak bisa dipakai ulang.
        """
        _INVALID = HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kode tidak valid atau sudah kedaluwarsa.",
        )

        user = await repo.get_by_email(email)
        if not user:
            raise _INVALID

        record = await repo.get_active_reset_pin(user.id)
        if not record:
            raise _INVALID

        if not self.verify_password(pin, record.pin_hash):
            raise _INVALID

        # Tandai PIN sudah dipakai — tidak bisa diverifikasi ulang
        await repo.mark_reset_pin_used(record)

        # Terbitkan reset_token: JWT pendek, type khusus, payload minimal
        expire_seconds = RESET_TOKEN_EXPIRE_MINUTES * 60
        expire_at = datetime.now(timezone.utc) + \
            timedelta(seconds=expire_seconds)
        payload = {
            "sub": str(user.id),
            "type": RESET_TOKEN_TYPE,
            "exp": expire_at,
            "jti": secrets.token_hex(16),   # cegah reuse
        }
        reset_token = jwt.encode(
            payload, self.reset_secret_key, algorithm=ALGORITHM
        )
        return ResetTokenResponse(reset_token=reset_token, expires_in=expire_seconds)

    async def reset_password(self, reset_token: str, new_password: str, repo: AuthRepository) -> MessageResponse:
        """
        Verifikasi reset_token lalu simpan password baru.
        Token hanya berlaku sekali — setelah dipakai tidak ada mekanisme
        reuse karena PIN sudah di-mark used_at pada tahap verify.
        """
        try:
            payload = jwt.decode(
                reset_token, self.reset_secret_key, algorithms=[ALGORITHM]
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Reset token tidak valid atau sudah kedaluwarsa.",
            )

        if payload.get("type") != RESET_TOKEN_TYPE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan reset token.",
            )

        user = await repo.get_by_id(UUID(payload["sub"]))
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User tidak ditemukan atau tidak aktif.",
            )

        user.hashed_password = self.hash_password(new_password)
        await repo.save(user)
        return MessageResponse(message="Password berhasil direset. Silakan login dengan password baru.")


# ------------------------------------------------------------------ #
#  FastAPI Dependencies                                                #
# ------------------------------------------------------------------ #
_auth_service = AuthService()


async def get_current_user(
    token: str = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> UserORM:
    """
    Dependency: ekstrak & validasi JWT access token dari header Authorization.
    """
    payload = _auth_service.decode_access_token(token)

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak mengandung identitas user.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    repo = AuthRepository(db)
    user = await repo.get_by_id(UUID(user_id))

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User tidak ditemukan.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun tidak aktif.",
        )
    return user


async def require_admin(
    current_user: UserORM = Depends(get_current_user),
) -> UserORM:
    """
    Dependency: pastikan user yang sedang login memiliki role admin.
    """
    if current_user.role != RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya admin yang dapat melakukan aksi ini.",
        )
    return current_user
