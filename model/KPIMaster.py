# ------------------------------------------------------------------ #
#  Tabel: kpi_master_records                                           #
# ------------------------------------------------------------------ #
from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from databaseConfig import Base


class KPIMasterORM(Base):
    __tablename__ = "kpi_master_records"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, index=True, default=uuid4)
    tahun: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kpi_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    definisi_operasional: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dihitung: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tidak_dihitung: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rumus: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sumber_data: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    achieve: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    partial: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fail: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    responsibility_persons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_sheet_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_sheet_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
