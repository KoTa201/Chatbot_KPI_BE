"""
model/SchedulerConfig.py

Konfigurasi scheduler untuk proses ingestion otomatis.
Tidak ada FK relationship ke IngestionLog — logs standalone dengan scheduler_id sebagai data saja.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from model.Base import Base


class SchedulerConfigORM(Base):
    __tablename__ = "scheduler_configs"

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    interval_value: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<SchedulerConfig id={self.id} enabled={self.is_enabled}>"
