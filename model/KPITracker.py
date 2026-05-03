"""
model/KPITracker.py

Changelog:
  v2 → v3:
    - Tambah FK user_id → users.id (nullable, ON DELETE SET NULL).
      Menggantikan kolom nama_orang (string bebas) dengan referensi ke tabel users.
    - HAPUS: nama_orang (sudah di-migrate ke user_id lewat Alembic migration).
    - HAPUS: responsibility_person (tidak pernah ada di ORM, tapi dihapus dari DB
      via migration jika kolom tersebut eksis).
    - Index composite diperbarui:
        ix_kpitracker_group_user  (group_id, user_id)
        ix_kpitracker_master_user (kpi_master_id, user_id)
      menggantikan index lama berbasis nama_orang.
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
    from model.KPIMaster import KPIMaster
    from model.User import User


class KPITracker(Base):
    __tablename__ = "kpi_tracker_records"

    __table_args__ = (
        # Query: siapa saja yang punya realisasi di sheet tracker ini?
        Index("ix_kpitracker_group_user", "group_id", "user_id"),
        # Query: semua realisasi untuk satu definisi KPI, lintas user
        Index("ix_kpitracker_master_user", "kpi_master_id", "user_id"),
        # Query: semua realisasi milik satu user (lintas group/KPI)
        Index("ix_kpitracker_user_id", "user_id"),
        # BRIN — tabel append-only, range scan by waktu
        Index("ix_kpitracker_created_brin", "created_at", postgresql_using="brin"),
    )

    id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )

    # FK 1: grup tracker
    group_id: Mapped[UUID] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # FK 2: KPI master
    kpi_master_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("kpi_master_records.id", ondelete="SET NULL"),
        nullable=True,
    )

    # FK 3: user pemilik realisasi — menggantikan nama_orang
    # nullable=True: data lama mungkin belum ter-migrasi
    # ON DELETE SET NULL: jika user dihapus, realisasi tetap ada
    user_id: Mapped[Optional[UUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_kpitracker_user_id"),
        nullable=True,
        comment="Karyawan pemilik realisasi ini; menggantikan kolom nama_orang.",
    )

    # Data realisasi
    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    bulan_num: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    realisasi: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
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
    kpi_master: Mapped[Optional["KPIMaster"]] = relationship(
        "KPIMaster", back_populates="tracker_records"
    )
    user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="select",
    )

    def __repr__(self) -> str:
        return (
            f"<KPITracker id={self.id} master={self.kpi_master_id} "
            f"user={self.user_id} tahun={self.tahun} bulan={self.bulan_num}>"
        )