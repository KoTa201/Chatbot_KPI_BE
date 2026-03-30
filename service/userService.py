"""
services/auth_service.py
Logika bisnis authentication:
- Password hashing & verification (bcrypt langsung, tanpa passlib)
- JWT access token — generate & decode
- Dependency FastAPI untuk mendapatkan current user dari token
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from databaseConfig import get_db
from model.User import RoleEnum, UserORM
from repository.userRepository import AuthRepository

# ------------------------------------------------------------------ #
#  Konfigurasi                                                         #
# ------------------------------------------------------------------ #

ALGORITHM = "HS256"
TOKEN_TYPE = "bearer"

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class AuthService:
    """
    Service untuk semua operasi authentication & otorisasi.

    Menggunakan bcrypt langsung (tanpa passlib) untuk kompatibilitas
    dengan bcrypt >= 4.x di Python 3.10+.

    Penggunaan di controller:
        service = AuthService()
        hashed  = service.hash_password(plain)
        token   = service.create_access_token(user_id=1, role="admin")
    """

    # ------------------------------------------------------------------ #
    #  Password                                                            #
    # ------------------------------------------------------------------ #

    def hash_password(self, plain_password: str) -> str:
        """
        Hash password plaintext menggunakan bcrypt.
        Password di-encode ke bytes sebelum di-hash.
        """
        password_bytes = plain_password.encode("utf-8")
        hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        return hashed.decode("utf-8")

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verifikasi plaintext vs hash bcrypt.
        Return True jika cocok, False jika tidak.
        """
        password_bytes = plain_password.encode("utf-8")
        hashed_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(password_bytes, hashed_bytes)

    # ------------------------------------------------------------------ #
    #  JWT Token                                                           #
    # ------------------------------------------------------------------ #

    def create_access_token(
        self,
        user_id: int,
        username: str,
        role: RoleEnum,
        expires_delta: Optional[timedelta] = None,
    ) -> tuple[str, int]:
        """
        Buat JWT access token.

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
            "exp": expire_at,
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
        return token, expire_seconds

    def decode_access_token(self, token: str) -> dict:
        """
        Decode dan validasi JWT token.
        Raise HTTP 401 jika token tidak valid atau kadaluarsa.
        """
        try:
            payload = jwt.decode(token, settings.SECRET_KEY,
                                 algorithms=[ALGORITHM])
            return payload
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token tidak valid atau sudah kadaluarsa.",
                headers={"WWW-Authenticate": "Bearer"},
            )

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
        Verifikasi credential. Field `identifier` bisa berupa username atau email —
        deteksi otomatis berdasarkan ada/tidaknya karakter '@'.
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
    Dependency: ekstrak & validasi JWT dari header Authorization.
    Inject ke endpoint yang membutuhkan autentikasi.
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
    user = await repo.get_by_id(int(user_id))

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
    Raise HTTP 403 jika bukan admin.

    Penggunaan:
        @router.post("/users")
        async def create_user(admin: UserORM = Depends(require_admin)):
            ...
    """
    if current_user.role != RoleEnum.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akses ditolak. Hanya admin yang dapat melakukan aksi ini.",
        )
    return current_user
