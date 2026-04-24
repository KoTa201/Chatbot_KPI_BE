import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String, Text, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from databaseConfig import Base

if TYPE_CHECKING:
    from model.User import UserORM


class ChatbotAuditLog(Base):
    __tablename__ = "chatbot_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    wireguard_status: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # 'PASS' | 'FAIL'
    wireguard_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # 'success' | 'error' | 'timeout'
    rows_returned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationship
    user: Mapped["UserORM"] = relationship(
        "UserORM", back_populates="audit_logs", lazy="noload"
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} user={self.user_id} "
            f"wg={self.wireguard_status} exec={self.execution_status}>"
        )
