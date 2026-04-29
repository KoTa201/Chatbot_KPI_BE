"""
model/IngestionLog.py

Desain: IngestionLog merekam audit trail setiap proses ingestion data.
- kpi_group_id: UUID grup (sheet) yang diproses
- Tanpa FK constraint: log tetap ada meskipun group dihapus (audit trail preserved)
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint, DateTime,
    Index, Integer, String, Text
)
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from model.Base import Base


class IngestionLogORM(Base):
    __tablename__ = "ingestion_logs"

    __table_args__ = (
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
        # Validasi source_type di level DB
        CheckConstraint(
            "source_type IN ('master', 'tracker')",
            name="ck_ingestion_source_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # kpi_group_id — grup (sheet) yang diproses (tanpa FK constraint)
    kpi_group_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        nullable=True,
        index=True,
    )

    # source_type — disimpan saat create agar filter tetap bekerja meski group dihapus
    source_type: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True, index=True
    )

    # group_name — nama grup saat ingest, agar sheet_name tetap tampil meski group dihapus
    group_name: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
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

    def __repr__(self) -> str:
        return (
            f"<IngestionLog id={self.id} group={self.kpi_group_id} "
            f"status='{self.status}' {self.ingested_count}/{self.total_rows}>"
        )
