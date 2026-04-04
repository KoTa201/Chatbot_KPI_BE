# ------------------------------------------------------------------ #
#  Tabel: ingestion_logs                                               #
# ------------------------------------------------------------------ #
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from databaseConfig import Base


class IngestionLogORM(Base):
    __tablename__ = "ingestion_logs"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, index=True, default=uuid4)
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    sheet_id: Mapped[str] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=True)
    nama_orang: Mapped[str] = mapped_column(String(255), nullable=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="success")
    source_type: Mapped[str] = mapped_column(String(50), default="kpi_tracker")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
