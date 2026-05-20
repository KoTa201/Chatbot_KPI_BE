import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatSession import ChatSession
    from model.ClarificationQuestion import ClarificationQuestion


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    is_sender_chatbot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    send_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages", lazy="noload"
    )
    clarification_questions: Mapped[list["ClarificationQuestion"]] = relationship(
        "ClarificationQuestion",
        back_populates="message_ref",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<ChatMessage message_id={self.message_id} session={self.session_id}>"
