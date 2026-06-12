import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ClarificationQuestion import ClarificationQuestion


class ClarificationAnswerOption(Base):
    __tablename__ = "clarification_question_answer_options"

    id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clarification_question_id: Mapped[uuid.UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("clarification_questions.clarification_question_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    option_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    clarification_question: Mapped["ClarificationQuestion"] = relationship(
        "ClarificationQuestion",
        back_populates="answer_options",
    )
