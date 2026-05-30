"""
model/PasswordReset.py
Menyimpan PIN reset password yang sudah di-hash.
Satu baris aktif per user — request baru menimpa yang lama.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID
from sqlalchemy import UUID as SAUUID

from sqlalchemy import DateTime, ForeignKey,  String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base
if TYPE_CHECKING:
    from model.User import User


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(
        "User", back_populates="password_resets")
