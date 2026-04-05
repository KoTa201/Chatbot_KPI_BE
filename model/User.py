"""
models/user_model.py
SQLAlchemy ORM model untuk tabel users.
"""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import UUID, Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from databaseConfig import Base
from model.PasswordReset import PasswordResetORM
if TYPE_CHECKING:
    from model.PasswordReset import PasswordResetORM


class RoleEnum(str, enum.Enum):
    admin = "admin"
    hrd = "hrd"
    kepala_divisi = "kepala_divisi"
    karyawan = "karyawan"


class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        UUID, primary_key=True, index=True, default=uuid4)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum), default=RoleEnum.karyawan, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    password_resets: Mapped[list["PasswordResetORM"]] = relationship(
        "PasswordResetORM", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
