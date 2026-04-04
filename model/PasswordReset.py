"""
model/PasswordReset.py
Menyimpan PIN reset password yang sudah di-hash.
Satu baris aktif per user — request baru menimpa yang lama.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from databaseConfig import Base
if TYPE_CHECKING:
    from model.User import UserORM


class PasswordResetORM(Base):
    __tablename__ = "password_resets"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pin_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)

    user: Mapped["UserORM"] = relationship(
        "UserORM", back_populates="password_resets")
