"""
schemas/ingestion_schema.py
Pydantic models untuk request/response endpoint ingestion.
"""

from typing import Optional, List, Any
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


class SheetIngestionResult(BaseModel):
    """Hasil ingestion per-sheet."""
    log_id:     Optional[int] = None
    sheet_name: str
    meta:       Optional[SheetMeta] = None
    total_rows: Optional[int] = None
    ingested:   Optional[int] = None
    failed:     Optional[int] = None
    errors:     Optional[List[Any]] = None
    status:     str                          # success / partial / failed / skipped
    reason:     Optional[str] = None         # diisi jika status = skipped


class BulkIngestionResponse(BaseModel):
    """Response untuk ingest semua sheet sekaligus."""
    spreadsheet_url:        str
    total_sheets_processed: int
    grand_total_rows:       int
    grand_ingested:         int
    grand_failed:           int
    overall_status:         str
    sheets:                 List[SheetIngestionResult]
