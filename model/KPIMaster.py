"""
model/KPIMaster.py

Perubahan dari versi sebelumnya:
- Tambah FK `group_id` → kpi_groups.id
  Kolom source_sheet_id / source_sheet_name DIHAPUS dari sini —
  informasi sheet sudah ada di kpi_groups, tidak perlu diulang per baris.
- UniqueConstraint(group_id, kpi_name) menggantikan (kpi_name, tahun):
  dalam satu sheet (grup), tidak boleh ada nama KPI yang sama dua kali.
- Composite index (group_id, kpi_name) — query paling umum:
  "semua KPI dalam sheet/grup ini"
- Kolom `tahun` dan `category` DIPERTAHANKAN di sini karena satu sheet
  bisa berisi KPI dari tahun/kategori yang berbeda-beda (sesuai konteks bisnis).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from model.Base import Base

if TYPE_CHECKING:
    from model.KPIGroup import KPIGroupORM
    from model.KPITracker import KPITrackerORM


class KPIMasterORM(Base):
    __tablename__ = "kpi_master_records"

    __table_args__ = (
        # Dalam satu grup/sheet, nama KPI harus unik
        UniqueConstraint("group_id", "kpi_name",
                         name="uq_kpimaster_group_name"),
        # Query: semua KPI dalam grup ini, filter by category
        Index("ix_kpimaster_group_category", "group_id", "category"),
    )

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # FK ke kpi_groups — sumber sheet dari mana KPI ini berasal
    # RESTRICT: master tidak bisa ada tanpa grupnya
    group_id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # tahun dan category TETAP di master karena satu sheet bisa campur
    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    kpi_name: Mapped[str] = mapped_column(String(255), nullable=False)

    definisi_operasional: Mapped[Optional[str]
                                 ] = mapped_column(Text, nullable=True)

    target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    achieve: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    partial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fail: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    responsibility_persons: Mapped[Optional[str]
                                   ] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    group: Mapped["KPIGroupORM"] = relationship(
        "KPIGroupORM", back_populates="master_records"
    )
    tracker_records: Mapped[list["KPITrackerORM"]] = relationship(
        "KPITrackerORM",
        back_populates="kpi_master",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<KPIMaster id={self.id} kpi='{self.kpi_name}' "
            f"tahun={self.tahun} group={self.group_id}>"
        )
