"""
model/IngestionLog.py

Desain: setiap log ingestion terikat ke satu KPIGroup (FK formal).
- kpi_group_id → kpi_groups.id  : grup (sheet) yang diproses
- scheduler_id  → scheduler_configs.id (nullable) : diisi jika dipicu scheduler

Info sheet (url, id, name) tidak lagi disimpan di sini karena sudah ada di KPIGroup.
Audit trail: JOIN ke kpi_groups untuk mendapatkan sheet_url/nama_grup.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Index, Integer, String, Text
)
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from databaseConfig import Base

if TYPE_CHECKING:
    from model.KPIGroup import KPIGroupORM
    from model.SchedulerConfig import SchedulerConfigORM


class IngestionLogORM(Base):
    __tablename__ = "ingestion_logs"

    __table_args__ = (
        # Monitoring: status ingestion per scheduler
        Index("ix_ingestion_scheduler_status", "scheduler_id", "status"),
        # Range scan by waktu — tabel append-only
        Index("ix_ingestion_created_brin",
              "created_at", postgresql_using="brin"),
        # Index per grup — audit: semua log untuk satu KPIGroup
        Index("ix_ingestion_kpi_group", "kpi_group_id", "created_at"),
        # Validasi status di level DB
        CheckConstraint(
            "status IN ('success', 'failed')",
            name="ck_ingestion_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # FK ke KPIGroup — grup (sheet) yang diproses
    kpi_group_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_groups.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # FK ke SchedulerConfig — diisi hanya jika ingestion dipicu scheduler
    scheduler_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("scheduler_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── STATISTIK INGESTION ──────────────────────────────────────────────────
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ingested_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False)
    errors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status: hanya success / failed
    status: Mapped[str] = mapped_column(
        String(20), default="failed", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    kpi_group: Mapped["KPIGroupORM"] = relationship("KPIGroupORM")
    scheduler: Mapped[Optional["SchedulerConfigORM"]] = relationship(
        "SchedulerConfigORM", back_populates="ingestion_logs"
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionLog id={self.id} group={self.kpi_group_id} "
            f"status='{self.status}' {self.ingested_count}/{self.total_rows}>"
        )
