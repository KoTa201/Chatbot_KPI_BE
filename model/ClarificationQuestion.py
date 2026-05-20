import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"

    clarification_question_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ambiguous_phrase: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ambiguity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    clarification_question: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_options: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_answer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
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
    def clarification_answer(self) -> int | None:
        return self.user_answer

    def __repr__(self) -> str:
        return (
            "<ClarificationQuestion "
            f"clarification_question_id={self.clarification_question_id}>"
        )
