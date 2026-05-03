"""
model/KPIMaster.py

Changelog:
  v2 → v3:
    - Tambah FK user_id → users.id (nullable, ON DELETE SET NULL).
      Merepresentasikan PIC utama dari responsibility_persons.
    - Index ix_kpimaster_user_id ditambahkan untuk efisiensi query
      "semua KPI yang dimiliki user X".
    - responsibility_persons DIPERTAHANKAN sebagai legacy text field
      (bisa berisi beberapa nama, comma-separated).
      Kolom ini akan deprecated setelah semua data ter-migrasi ke user_id.
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
    from model.KPIGroup import KPIGroup
    from model.KPITracker import KPITrackerORM
    from model.User import User


class KPIMasterORM(Base):
    __tablename__ = "kpi_master_records"

    __table_args__ = (
        # Dalam satu grup/sheet, nama KPI harus unik
        UniqueConstraint("group_id", "kpi_name", name="uq_kpimaster_group_name"),
        # Query: semua KPI dalam grup ini, filter by category
        Index("ix_kpimaster_group_category", "group_id", "category"),
        # Query: semua KPI milik/PIC user tertentu
        Index("ix_kpimaster_user_id", "user_id"),
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

    # FK ke users — PIC utama KPI ini
    # nullable=True: data lama mungkin belum ter-migrasi
    # ON DELETE SET NULL: jika user dihapus, KPI tetap ada (PIC dikosongkan)
    user_id: Mapped[Optional[SAUUID]] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_kpimaster_user_id"),
        nullable=True,
        comment="PIC utama; migrasi dari responsibility_persons (nama pertama).",
    )

    tahun: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(255), nullable=False)
    kpi_name: Mapped[str] = mapped_column(String(255), nullable=False)

    definisi_operasional: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    achieve: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    partial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fail: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    group: Mapped["KPIGroup"] = relationship(
        "KPIGroup", back_populates="master_records"
    )
    user: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[user_id],
        lazy="select",
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
            f"tahun={self.tahun} group={self.group_id} user={self.user_id}>"
        )