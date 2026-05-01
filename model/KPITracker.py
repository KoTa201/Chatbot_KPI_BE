"""
model/KPITracker.py

Perubahan dari versi sebelumnya:
- Tambah FK `group_id` → kpi_groups.id (grup tracker sheet-nya sendiri)
- Tambah FK `kpi_master_id` → kpi_master_records.id (relasi ke definisi KPI)
- HAPUS: nama_kpi (string redundan), tahun, source_sheet_id, source_sheet_name
  Semua info ini sudah bisa didapat lewat JOIN ke group dan master.
- Composite index (group_id, nama_orang) — query: semua realisasi dalam
  sheet tracker ini untuk orang tertentu
- Composite index (kpi_master_id, nama_orang) — query: realisasi KPI X
  oleh karyawan Y, lintas sheet
- BRIN pada created_at — tabel append-only, tumbuh besar

Catatan desain — dua FK sekaligus (group_id dan kpi_master_id):
  Tracker punya DUA konteks yang independen:
  1. group_id  → "data ini berasal dari sheet tracker mana?"
  2. kpi_master_id → "data ini realisasi untuk KPI definisi mana?"
  Keduanya dibutuhkan karena master dan tracker berasal dari sheet berbeda.
  Tanpa group_id di tracker, kita tidak tahu sheet tracker mana sumber datanya.
  Tanpa kpi_master_id, kita tidak bisa JOIN ke definisi KPI (rumus, target, dll).
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from model.Base import Base

if TYPE_CHECKING:
    from model.KPIGroup import KPIGroup
    from model.KPIMaster import KPIMasterORM


class KPITrackerORM(Base):
    __tablename__ = "kpi_tracker_records"

    __table_args__ = (
        # Query: siapa saja yang punya realisasi di sheet tracker ini?
        Index("ix_kpitracker_group_orang", "group_id", "nama_orang"),
        # Query: semua realisasi untuk satu definisi KPI, lintas orang
        Index("ix_kpitracker_master_orang", "kpi_master_id", "nama_orang"),
        # BRIN — tabel append-only, range scan by waktu
        Index("ix_kpitracker_created_brin",
              "created_at", postgresql_using="brin"),
    )

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # FK 1: grup tracker — "data ini dari sheet tracker mana?"
    group_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # FK 2: KPI master — "ini realisasi dari definisi KPI mana?"
    # nullable=True untuk toleransi data yang belum bisa di-match ke master
    kpi_master_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_master_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Data realisasi
    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    bulan_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    realisasi: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True)
    nama_orang: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True)
    keterangan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    group: Mapped["KPIGroup"] = relationship(
        "KPIGroup", back_populates="tracker_records"
    )
    kpi_master: Mapped[Optional["KPIMasterORM"]] = relationship(
        "KPIMasterORM", back_populates="tracker_records"
    )

    def __repr__(self) -> str:
        return (
            f"<KPITracker id={self.id} master={self.kpi_master_id} "
            f"orang='{self.nama_orang}'>"
        )
