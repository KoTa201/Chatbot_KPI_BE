"""
schemas/ingestion_schema.py
Pydantic models untuk request/response endpoint ingestion.
"""

from typing import Optional
from pydantic import BaseModel


class SheetMeta(BaseModel):
    nama_orang: Optional[str]
    bulan: Optional[str]
    bulan_num: Optional[int]
    tahun: Optional[int]


class IngestionResponse(BaseModel):
    log_id: int
    sheet_id: str
    sheet_name: str
    meta: SheetMeta
    total_rows: int
    ingested: int
    failed: int
    errors: list[str]
    status: str
