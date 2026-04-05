"""
schemas/auth_schema.py
Pydantic models untuk request/response endpoint authentication.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from model.User import RoleEnum


# ------------------------------------------------------------------ #
#  Request Schemas                                                     #
# ------------------------------------------------------------------ #

class UserCreateRequest(BaseModel):
    """Payload untuk admin menambahkan user baru."""
    username: str = Field(..., min_length=3, max_length=100,
                          pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: RoleEnum = RoleEnum.karyawan

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError(
                "Password harus mengandung minimal 1 huruf kapital.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password harus mengandung minimal 1 angka.")
        return v


class LoginRequest(BaseModel):
    """
    Payload untuk login.
    Field `identifier` bisa diisi username atau email.
    """
    identifier: str = Field(
        ...,
        min_length=3,
        max_length=255,
        description="Username atau email yang terdaftar.",
    )
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    """Payload untuk ganti password diri sendiri."""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError(
                "Password baru harus mengandung minimal 1 huruf kapital.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password baru harus mengandung minimal 1 angka.")
        return v


class UpdateUserRequest(BaseModel):
    """Payload untuk admin mengupdate data user (semua field opsional)."""
    full_name: Optional[str] = Field(
        default=None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[RoleEnum] = None
    is_active: Optional[bool] = None


# ------------------------------------------------------------------ #
#  Response Schemas                                                    #
# ------------------------------------------------------------------ #

class UserResponse(BaseModel):
    """Data user yang dikembalikan ke client (tanpa password)."""
    id: UUID
    username: str
    email: str
    full_name: str
    role: RoleEnum
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Response setelah login berhasil."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int           # detik
    user: UserResponse


class MessageResponse(BaseModel):
    """Response generik untuk operasi yang tidak mengembalikan data."""
    message: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    # None saat rotate hanya return user-less response
    refresh_token: str | None = None
    refresh_expires_in: int | None = None
    # None saat /refresh (tidak perlu kirim ulang)
    user: UserResponse | None = None

# Tambahkan ke file schema yang sudah ada


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetPinRequest(BaseModel):
    email: EmailStr
    pin: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=8)


class ResetTokenResponse(BaseModel):
    reset_token: str
    expires_in: int  # detik
