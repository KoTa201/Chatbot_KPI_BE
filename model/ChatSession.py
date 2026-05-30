import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base
from utils.datetime import utc_now

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage
    from model.Chatbot import Chatbot
    from model.User import User


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chatbot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chatbots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="sessions", lazy="noload"
    )
    chatbot: Mapped["Chatbot"] = relationship(
        "Chatbot", back_populates="sessions", lazy="noload"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    @property
    def id(self) -> uuid.UUID:
        return self.session_id

    @property
    def title(self) -> str:
        return self.session_name

    @property
    def created_at(self) -> datetime:
        return self.start_at

    @property
    def updated_at(self) -> datetime:
        return self.end_at or self.start_at

    def __repr__(self) -> str:
        return (
            f"<ChatSession session_id={self.session_id} "
            f"session_name={self.session_name!r} user={self.user_id}>"
        )
