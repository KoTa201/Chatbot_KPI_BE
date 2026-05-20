"""
model/ClarificationLog.py
ORM model untuk tracking semua aktivitas clarification mechanism.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Numeric, String, Text, UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from model.Base import Base


class ClarificationLogORM(Base):
    __tablename__ = "clarification_logs"

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Session & User Context
    session_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), nullable=False, index=True)
    user_role: Mapped[str] = mapped_column(String(50), nullable=False)

    # Query Content
    original_query: Mapped[str] = mapped_column(Text, nullable=False)

    # Ambiguity Detection
    ambiguity_score: Mapped[float] = mapped_column(
        Numeric(3, 2), nullable=False)
    ambiguity_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Decision Tracking
    decision: Mapped[str] = mapped_column(
        String(10), nullable=False)  # "clarify" atau "direct"
    decision_source: Mapped[str] = mapped_column(
        String(20), nullable=False)  # "rules", "llm", atau "llm_fallback"

    # Clarification Data
    clarifying_question: Mapped[Optional[str]
                                ] = mapped_column(Text, nullable=True)
    clarification_answer: Mapped[Optional[str]
                                 ] = mapped_column(Text, nullable=True)
    disambiguated_query: Mapped[Optional[str]
                                ] = mapped_column(Text, nullable=True)

    # User Feedback (untuk evaluasi)
    user_feedback: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True)
    needed_correction: Mapped[Optional[bool]
                              ] = mapped_column(Boolean, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ClarificationLog id={self.id} session={self.session_id} "
            f"decision={self.decision} ambiguity_type={self.ambiguity_type}>"
        )
