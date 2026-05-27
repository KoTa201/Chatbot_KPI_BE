"""
models/user_model.py
SQLAlchemy ORM model untuk tabel users.
"""

from datetime import datetime
from typing import TYPE_CHECKING
import uuid
from uuid import uuid4

from sqlalchemy import UUID, Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from model.Base import Base, RoleEnum
from model.PasswordReset import PasswordReset
from utils.datetime import utc_now
if TYPE_CHECKING:
    from model.ChatSession import ChatSession


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, index=True, default=uuid4)
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleEnum] = mapped_column(
        Enum(RoleEnum, native_enum=False), default=RoleEnum.karyawan, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    password_resets: Mapped[list["PasswordReset"]] = relationship(
        "PasswordReset", back_populates="user", cascade="all, delete-orphan"
    )

    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="user", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
