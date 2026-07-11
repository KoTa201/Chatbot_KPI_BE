"""
services/auth_service.py
Logika bisnis authentication:
- Password hashing & verification (bcrypt langsung, tanpa passlib)
- JWT access token — generate & decode
- Refresh token — generate, decode, rotate & revoke
- Dependency FastAPI untuk mendapatkan current user dari token
"""

from datetime import timedelta
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

from exceptions import BadRequestError, ForbiddenError, UnauthorizedError
from model.PasswordReset import PasswordReset
from service.emailService import EmailService

from configCredidential import settings
from databaseConfig import get_db
from model.User import RoleEnum, User
from repository.userRepository import UserRepository
from utils.datetime import utc_now

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthService:
    def __init__(
        self,
        db: AsyncSession | None = None,
        repo: UserRepository | None = None,
    ):

        self.repo: UserRepository = UserRepository(db)
        self.secret_key: str = settings.SECRET_KEY
        self.refresh_secret_key: str = settings.REFRESH_SECRET_KEY
        self.reset_secret_key: str = settings.RESET_SECRET_KEY
        self.access_token_expire_minutes: int = settings.ACCESS_TOKEN_EXPIRE_MINUTES
        self.refresh_token_expire_days: int = settings.REFRESH_TOKEN_EXPIRE_DAYS
        self.algorithm: str = settings.AUTH_ALGORITHM
        self.token_type: str = settings.AUTH_TOKEN_TYPE
        self.refresh_token_type: str = settings.AUTH_REFRESH_TOKEN_TYPE
        self.reset_token_type: str = settings.AUTH_RESET_TOKEN_TYPE
        self.pin_expire_minutes: int = settings.AUTH_PIN_EXPIRE_MINUTES
        self.reset_token_expire_minutes: int = settings.AUTH_RESET_TOKEN_EXPIRE_MINUTES


    # ------------------------------------------------------------------ #
    #  JWT — Refresh Token                                                 #
    # ------------------------------------------------------------------ #
    def create_access_token(
        self,
        user_id: UUID,
        username: str,
        role: RoleEnum,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, int]:
        expire_seconds = (
            int(expires_delta.total_seconds())
            if expires_delta
            else self.access_token_expire_minutes * 60
        )
        expire_at = utc_now() + timedelta(seconds=expire_seconds)

        payload = {
            "sub": str(user_id),
            "username": username,
            "role": role.value,          # disimpan sebagai string
            "type": "access",
            "exp": expire_at,
            "jti": str(uuid.uuid4()),
        }

        token = jwt.encode(
            payload, self.secret_key, algorithm=self.algorithm
        )
        return token, expire_seconds

    def decode_access_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token tidak valid atau sudah kadaluarsa.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token bukan access token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if "jti" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak memiliki ID unik.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Pastikan exp ada dan valid (walaupun jwt.decode sudah mengecek expiry)
        if "exp" not in payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak memiliki expiry timestamp.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return payload

    def create_refresh_token(
        self,
        user_id: UUID,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, int]:
        expire_seconds = (
            int(expires_delta.total_seconds())
            if expires_delta
            else self.refresh_token_expire_days * 86_400
        )
        expire_at = utc_now() + \
            timedelta(seconds=expire_seconds)

        payload = {
            "sub": str(user_id),
            "type": self.refresh_token_type,  # ← tandai sebagai refresh token
            "exp": expire_at,
            "jti": str(uuid.uuid4()),
        }

        token = jwt.encode(
            payload, self.refresh_secret_key, algorithm=self.algorithm
        )
        return token, expire_seconds

    def decode_refresh_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(
                token, self.refresh_secret_key, algorithms=[self.algorithm]
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token tidak valid atau sudah kadaluarsa.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("type") != self.refresh_token_type:
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
        repo: UserRepository,
    ) -> tuple[str, int, str, int]:
        repo = repo or self.repo
        payload = self.decode_refresh_token(refresh_token)

        user_id = UUID(payload["sub"])

        # Cek denylist — deteksi token reuse
        if await repo.is_token_revoked(refresh_token):
            raise UnauthorizedError(
                "Refresh token sudah digunakan atau dicabut. Silakan login ulang."
            )

        # Revoke token lama sebelum menerbitkan yang baru
        await repo.revoke_token(refresh_token, user_id)

        # Ambil user terbaru (role bisa berubah sejak token dibuat)
        user = await repo.get_by_id(user_id)
        if user is None:
            raise UnauthorizedError("User tidak ditemukan.")
        if not user.is_active:
            raise ForbiddenError("Akun tidak aktif.")

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
    ) -> None:
        payload = self.decode_refresh_token(refresh_token)
        user_id = UUID(payload["sub"])
        await self.repo.revoke_token(refresh_token, user_id)

    # ------------------------------------------------------------------ #
    #  User validation                                                     #
    # ------------------------------------------------------------------ #

    async def authenticate_user(
        self,
        identifier: str,
        password: str,
        repo: UserRepository | None = None,
    ) -> User:
        repo = repo or self.repo
        user = await repo.get_by_username_or_email(identifier)

        if not user or not self.verify_password(password, user.hashed_password):
            raise UnauthorizedError("Username/email atau password salah.")
        if not user.is_active:
            raise ForbiddenError("Akun tidak aktif. Hubungi administrator.")
        return user

    async def request_password_reset(self, email: str) -> str:
        user = await self.repo.get_by_username_or_email(email)
        if not user or not user.is_active:
            raise UnauthorizedError(
                f"User dengan email {email} tidak ditemukan atau tidak aktif."
            )

        pin = f"{random.SystemRandom().randint(0, 999_999):06d}"
        pin_hash = self.hash_password(pin)   # bcrypt — sama seperti password

        expires_at = utc_now() + \
            timedelta(minutes=self.pin_expire_minutes)
        record = PasswordReset(
            user_id=user.id,
            pin_hash=pin_hash,
            expires_at=expires_at,
        )
        await self.repo.create_reset_pin(record)

        EmailService().send_reset_pin_background(
            to_email=user.email,
            full_name=user.full_name or user.username,
            pin=pin,
        )
        return "Jika email terdaftar, kode reset akan dikirim dalam beberapa saat."

    async def verify_reset_pin(self, email: str, pin: str) -> tuple[str, int]:
        _INVALID = BadRequestError("Kode tidak valid atau sudah kedaluwarsa.")

        user = await self.repo.get_by_username_or_email(email)
        if not user:
            raise _INVALID

        record = await self.repo.get_active_reset_pin(user.id)
        if not record:
            raise _INVALID

        if not self.verify_password(pin, record.pin_hash):
            raise _INVALID

        # Tandai PIN sudah dipakai — tidak bisa diverifikasi ulang
        await self.repo.mark_reset_pin_used(record)

        # Terbitkan reset_token: JWT pendek, type khusus, payload minimal
        expire_seconds = self.reset_token_expire_minutes * 60
        expire_at = utc_now() + \
            timedelta(seconds=expire_seconds)
        payload = {
            "sub": str(user.id),
            "type": self.reset_token_type,
            "exp": expire_at,
            "jti": secrets.token_hex(16),   # cegah reuse
        }
        reset_token = jwt.encode(
            payload, self.reset_secret_key, algorithm=self.algorithm
        )
        return reset_token, expire_seconds

    async def reset_password(self, reset_token: str, new_password: str) -> str:
        try:
            payload = jwt.decode(
                reset_token, self.reset_secret_key, algorithms=[self.algorithm]
            )
        except JWTError:
            raise UnauthorizedError("Reset token tidak valid atau sudah kedaluwarsa.")

        if payload.get("type") != self.reset_token_type:
            raise UnauthorizedError("Token bukan reset token.")

        user = await self.repo.get_by_id(UUID(payload["sub"]))
        if not user or not user.is_active:
            raise UnauthorizedError("User tidak ditemukan atau tidak aktif.")

        user.hashed_password = self.hash_password(new_password)
        await self.repo.save(user)
        return "Password berhasil direset. Silakan login dengan password baru."

    @staticmethod
    def hash_password(plain_password: str) -> str:
        password_bytes = plain_password.encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        return hashed.decode("utf-8")

    @staticmethod
    def verify_password( plain_password: str, hashed_password: str) -> bool:
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)


_auth_service = AuthService(repo=UserRepository(Depends(get_db)))


async def get_current_user(
    token: str = Depends(_oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
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

    repo = UserRepository(db)
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
