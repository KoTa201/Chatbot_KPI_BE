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

from config import settings
from databaseConfig import get_db
from model.User import RoleEnum, UserORM
from repository.userRepository import AuthRepository

# ------------------------------------------------------------------ #
#  Konfigurasi                                                         #
# ------------------------------------------------------------------ #

ALGORITHM = "HS256"
TOKEN_TYPE = "bearer"
REFRESH_TOKEN_TYPE = "refresh"

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthService:
    """
    Service untuk semua operasi authentication & otorisasi.

    Menggunakan bcrypt langsung (tanpa passlib) untuk kompatibilitas
    dengan bcrypt >= 4.x di Python 3.10+.

    Penggunaan di controller:
        service = AuthService()
        hashed        = service.hash_password(plain)
        access, exp   = service.create_access_token(user_id=1, username="x", role=...)
        refresh, exp  = service.create_refresh_token(user_id=1)
    """

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
            else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
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
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
        return token, expire_seconds

    def decode_access_token(self, token: str) -> dict:
        """
        Decode dan validasi JWT access token.
        Raise HTTP 401 jika token tidak valid, kadaluarsa, atau bukan access token.
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY,
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
            else settings.REFRESH_TOKEN_EXPIRE_DAYS * 86_400
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
            payload, settings.REFRESH_SECRET_KEY, algorithm=ALGORITHM
        )
        return token, expire_seconds

    def decode_refresh_token(self, token: str) -> dict:
        """
        Decode dan validasi JWT refresh token.
        Raise HTTP 401 jika token tidak valid, kadaluarsa, atau bukan refresh token.
        """
        try:
            payload = jwt.decode(
                token, settings.REFRESH_SECRET_KEY, algorithms=[ALGORITHM]
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
