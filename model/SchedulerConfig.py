"""
model/SchedulerConfig.py — tidak ada perubahan struktural besar.
Minor: CheckConstraint interval_unit, server_default pada updated_at.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from databaseConfig import Base

if TYPE_CHECKING:
    from model.IngestionLog import IngestionLogORM


class SchedulerConfigORM(Base):
    __tablename__ = "scheduler_configs"

    __table_args__ = (
        CheckConstraint(
            "interval_unit IN ('hours', 'days', 'weeks', 'months')",
            name="ck_scheduler_interval_unit",
        ),
    )

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    interval_value: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    ingestion_logs: Mapped[list["IngestionLogORM"]] = relationship(
        "IngestionLogORM", back_populates="scheduler",
        cascade="all, delete-orphan", lazy="select",
    )

    def __repr__(self) -> str:
        return f"<SchedulerConfig id={self.id} enabled={self.is_enabled}>"
