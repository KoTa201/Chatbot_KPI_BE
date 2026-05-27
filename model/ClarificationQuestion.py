import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base
from utils.datetime import utc_now

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"

    clarification_question_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ambiguity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_ambiguity_level1_type_llm: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    clarification_question: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_options: Mapped[str | None] = mapped_column(String(255), nullable=True)
    selected_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    free_text_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    message_ref: Mapped["ChatMessage"] = relationship(
        "ChatMessage", back_populates="clarification_questions", lazy="noload"
    )

    @property
    def id(self) -> str:
        return self.clarification_question_id

    @property
    def clarifying_question(self) -> str:
        return self.clarification_question

    @property
    def clarification_answer(self) -> str | None:
        return self.selected_answer

    def __repr__(self) -> str:
        return (
            "<ClarificationQuestion "
            f"clarification_question_id={self.clarification_question_id}>"
        )
