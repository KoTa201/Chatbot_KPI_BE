# ------------------------------------------------------------------ #
#  Tabel: kpi_records                                                  #
# ------------------------------------------------------------------ #

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from databaseConfig import Base


class KPIRecordORM(Base):
    __tablename__ = "kpi_tracker_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nama_kpi = Column(String(255), nullable=False, index=True)
    tahun = Column(Integer, nullable=True, index=True)
    realisasi = Column(String(100), nullable=True)
    nama_orang = Column(String(255), nullable=True, index=True)
    keterangan = Column(Text, nullable=True)

    # Teks gabungan untuk keperluan RAG retrieval
    document_text = Column(Text, nullable=True)

    # Metadata sumber
    source_sheet_id = Column(String(255), nullable=True)
    source_sheet_name = Column(String(255), nullable=True)
    source_row = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
