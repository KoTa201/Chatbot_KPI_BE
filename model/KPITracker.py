# ------------------------------------------------------------------ #
#  Tabel: kpi_records                                                  #
# ------------------------------------------------------------------ #

from uuid import uuid4
from sqlalchemy import UUID, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from databaseConfig import Base


class KPIRecordORM(Base):
    __tablename__ = "kpi_tracker_records"

    id: Mapped[UUID] = mapped_column(
        UUID, primary_key=True, index=True, default=uuid4)
    nama_kpi: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True)
    tahun: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    realisasi: Mapped[str] = mapped_column(String(100), nullable=True)
    nama_orang: Mapped[str] = mapped_column(
        String(255), nullable=True, index=True)
    keterangan: Mapped[str] = mapped_column(Text, nullable=True)

    # Teks gabungan untuk keperluan RAG retrieval
    document_text: Mapped[str] = mapped_column(Text, nullable=True)

    # Metadata sumber
    source_sheet_id: Mapped[str] = mapped_column(String(255), nullable=True)
    source_sheet_name: Mapped[str] = mapped_column(String(255), nullable=True)
    source_row: Mapped[int] = mapped_column(Integer, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), onupdate=func.now())
