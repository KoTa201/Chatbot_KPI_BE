import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from model.Base import Base

if TYPE_CHECKING:
    from model.User import User


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
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

    user: Mapped["User"] = relationship(
        "User", back_populates="sessions", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} title={self.title!r} user={self.user_id}>"
