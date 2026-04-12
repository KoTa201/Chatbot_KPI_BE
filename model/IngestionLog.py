"""
model/IngestionLog.py

Perubahan dari versi sebelumnya — perubahan terbesar di file ini:

DESAIN POLYMORPHIC LOG:
  Satu tabel log merekam semua jenis ingestion:
    source_type = 'scheduler'   → ingestion dijadwalkan otomatis
    source_type = 'kpi_master'  → ingestion pertama saat KPIGroup master dibuat
    source_type = 'kpi_tracker' → ingestion pertama saat KPIGroup tracker dibuat

  Kolom `source_id` menyimpan UUID entitas yang memicu ingestion:
    - scheduler_id jika source_type = 'scheduler'
    - kpi_group_id jika source_type = 'kpi_master' atau 'kpi_tracker'

  Mengapa tidak pakai FK formal untuk source_id?
  Karena satu kolom tidak bisa memiliki FK ke dua tabel sekaligus di PostgreSQL.
  Sebagai gantinya, integritas dijaga di application layer:
    - Saat insert log, selalu isi source_type + source_id secara bersamaan
    - Gunakan CHECK constraint untuk pastikan source_type valid
    - Query audit: WHERE source_type = 'kpi_master' AND source_id = <group_id>

  Kolom `scheduler_id` tetap ada sebagai FK eksplisit khusus untuk
  source_type='scheduler', sehingga JOIN ke scheduler_configs tetap bisa
  dilakukan secara formal tanpa harus lewat source_id.

Composite index (source_type, source_id) — query audit lintas entitas.
Composite index (scheduler_id, status)   — query monitoring scheduler.
BRIN pada created_at                     — tabel append-only.
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
from model.Base import IngestionSourceType

if TYPE_CHECKING:
    from model.SchedulerConfig import SchedulerConfigORM


class IngestionLogORM(Base):
    __tablename__ = "ingestion_logs"

    __table_args__ = (
        # Audit: semua log dari satu entitas (grup atau scheduler)
        Index("ix_ingestion_source", "source_type", "source_id"),
        # Monitoring: status ingestion per scheduler
        Index("ix_ingestion_scheduler_status", "scheduler_id", "status"),
        # Range scan by waktu — tabel append-only
        Index("ix_ingestion_created_brin",
              "created_at", postgresql_using="brin"),
        # Validasi source_type di level DB
        CheckConstraint(
            "source_type IN ('scheduler', 'kpi_master', 'kpi_tracker')",
            name="ck_ingestion_source_type",
        ),
        # Validasi status di level DB
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_ingestion_status",
        ),
        # Jika source_type = 'scheduler', scheduler_id wajib diisi
        CheckConstraint(
            "NOT (source_type = 'scheduler' AND scheduler_id IS NULL)",
            name="ck_ingestion_scheduler_required",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # ── POLYMORPHIC SOURCE ───────────────────────────────────────────────────
    # source_type: tipe entitas yang memicu ingestion ini
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IngestionSourceType.SCHEDULER
    )
    # source_id: UUID entitas sumber (scheduler_id atau kpi_group_id)
    # Tidak ada FK formal karena polymorphic — dijaga di application layer
    source_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True), nullable=True
    )

    # FK eksplisit khusus scheduler — memungkinkan JOIN formal ke scheduler_configs
    # Diisi hanya jika source_type = 'scheduler'
    scheduler_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("scheduler_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── METADATA SHEET ───────────────────────────────────────────────────────
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    sheet_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True)

    # ── STATISTIK INGESTION ──────────────────────────────────────────────────
    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ingested_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False)
    errors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Status awal selalu 'running', diupdate saat selesai
    status: Mapped[str] = mapped_column(
        String(20), default="running", nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship formal ke scheduler (hanya relevan jika source_type='scheduler')
    scheduler: Mapped[Optional["SchedulerConfigORM"]] = relationship(
        "SchedulerConfigORM", back_populates="ingestion_logs"
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionLog id={self.id} type='{self.source_type}' "
            f"status='{self.status}' {self.ingested_count}/{self.total_rows}>"
        )
