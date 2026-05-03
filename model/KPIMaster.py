"""
model/KPIMaster.py

Changelog:
  v3 → v4:
    - Hapus FK user_id dan kolom terkait (user_id, ix_kpimaster_user_id,
      fk_kpimaster_user_id). PIC sebelumnya hanya menyimpan nama pertama.
    - Tambah relasi many-to-many ke User melalui tabel junction
      kpi_master_users. Satu KPI kini bisa memiliki lebih dari satu PIC,
      dan satu user bisa menjadi PIC di banyak KPI.
    - Tabel junction didefinisikan di modul ini dan di-import oleh
      repository untuk operasi INSERT/DELETE langsung.
    - responsibility_persons DIPERTAHANKAN sebagai legacy text field
      sampai seluruh data ter-migrasi.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy import Column
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from model.Base import Base

if TYPE_CHECKING:
    from model.KPIGroup import KPIGroup
    from model.KPITracker import KPITracker
    from model.User import User


# ---------------------------------------------------------------------------
# Association table — kpi_master_records ↔ users (many-to-many)
# ---------------------------------------------------------------------------
kpi_master_users = Table(
    "kpi_master_users",
    Base.metadata,
    Column(
        "kpi_master_id",
        SAUUID(as_uuid=True),
        ForeignKey("kpi_master_records.id", ondelete="CASCADE", name="fk_kpimasterusers_master"),
        primary_key=True,
    ),
    Column(
        "user_id",
        SAUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_kpimasterusers_user"),
        primary_key=True,
    ),
    # Index agar query "semua KPI milik user X" tetap efisien
    Index("ix_kpimasterusers_user_id", "user_id"),
)


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------
class KPIMaster(Base):
    __tablename__ = "kpi_master_records"

    __table_args__ = (
        # Dalam satu grup/sheet, nama KPI harus unik
        UniqueConstraint("group_id", "kpi_name", name="uq_kpimaster_group_name"),
        # Query: semua KPI dalam grup, filter by category
        Index("ix_kpimaster_group_category", "group_id", "category"),
    )

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # FK ke kpi_groups
    group_id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )

    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    kpi_name: Mapped[str] = mapped_column(String(255), nullable=False)

    definisi_operasional: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    achieve: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    partial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fail: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Legacy field — akan di-deprecated setelah semua data ter-migrasi
    responsibility_persons: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Nama PIC comma-separated (legacy). Gunakan relasi `pic_users` untuk data baru.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ───────────────────────────────────────────────────────
    group: Mapped["KPIGroup"] = relationship(
        "KPIGroup", back_populates="master_records"
    )

    # Many-to-many: PIC yang bertanggung jawab atas KPI ini
    pic_users: Mapped[list["User"]] = relationship(
        "User",
        secondary=kpi_master_users,
        lazy="select",
    )

    tracker_records: Mapped[list["KPITracker"]] = relationship(
        "KPITracker",
        back_populates="kpi_master",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<KPIMaster id={self.id} kpi='{self.kpi_name}' "
            f"tahun={self.tahun} group={self.group_id}>"
        )