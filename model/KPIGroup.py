"""
model/KPIGroup.py

Tabel BARU — jembatan antara kpi_master_records dan kpi_tracker_records.

Konteks bisnis:
  Satu grup = satu sheet Google Sheets. Sebuah sheet bisa berisi banyak
  KPI dengan category/tahun yang berbeda-beda. Group ini menjadi
  "header" bersama agar master dan tracker tidak perlu menyimpan
  ulang info sheet (sheet_id, sheet_name, sheet_url) di setiap baris.

Relasi:
  kpi_groups ──< kpi_master_records   (one-to-many)
  kpi_groups ──< kpi_tracker_records  (one-to-many)
  kpi_master_records ──< kpi_tracker_records  (tetap ada, untuk FK per baris)

Dengan desain ini:
  - kpi_master_records tidak perlu kolom source_sheet_id / source_sheet_name
  - kpi_tracker_records tidak perlu kolom tahun, source_sheet_id / source_sheet_name
  - Tidak ada redundansi info sheet di ribuan baris tracker
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from databaseConfig import Base

if TYPE_CHECKING:
    from model.KPIMaster import KPIMasterORM
    from model.KPITracker import KPITrackerORM


class KPIGroupORM(Base):
    __tablename__ = "kpi_groups"

    __table_args__ = (
        # Satu sheet_id unik per tipe grup (master vs tracker sheet beda)
        UniqueConstraint("sheet_id", "group_type",
                         name="uq_kpigroup_sheet_type"),
    )

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # Nama deskriptif grup — biasanya diambil dari nama sheet / tab
    nama_grup: Mapped[str] = mapped_column(String(255), nullable=False)

    # group_type: 'master' atau 'tracker' — satu sheet hanya boleh satu tipe
    # Ini penting karena master sheet dan tracker sheet adalah entitas berbeda
    group_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Metadata sheet sumber — disimpan di sini, TIDAK di setiap baris master/tracker
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    sheet_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Kolom khusus tracker — diabaikan untuk grup bertipe 'master'
    tahun: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_scheduled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

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
    master_records: Mapped[list["KPIMasterORM"]] = relationship(
        "KPIMasterORM",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="select",
    )
    tracker_records: Mapped[list["KPITrackerORM"]] = relationship(
        "KPITrackerORM",
        back_populates="group",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<KPIGroup id={self.id} nama='{self.nama_grup}' "
            f"type='{self.group_type}' sheet='{self.sheet_name}'>"
        )
