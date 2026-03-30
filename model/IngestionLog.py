# ------------------------------------------------------------------ #
#  Tabel: ingestion_logs                                               #
# ------------------------------------------------------------------ #
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from databaseConfig import Base


class IngestionLogORM(Base):
    __tablename__ = "ingestion_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sheet_url = Column(Text, nullable=False)
    sheet_id = Column(String(255), nullable=True)
    sheet_name = Column(String(255), nullable=True)
    nama_orang = Column(String(255), nullable=True)
    total_rows = Column(Integer, default=0)
    ingested_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    errors = Column(Text, nullable=True)   # JSON string
    # success | partial | failed
    status = Column(String(50), default="success")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
