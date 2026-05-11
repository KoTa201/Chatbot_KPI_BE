"""
schemas/kpiTrackerSchema.py
Pydantic models untuk request/response endpoint KPI Tracker management.
"""

from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, model_validator, ConfigDict


# ================================================================ #
#  REQUEST Schemas (Input Validation)                              #
# ================================================================ #

class CreateKPIRecordRequest(BaseModel):
    """Schema untuk create satu KPI record baru."""
    nama_kpi: str = Field(..., min_length=1, max_length=255,
                          description="Nama KPI (required)")
    tahun: Optional[int] = Field(
        None, ge=2000, le=2031, description="Tahun (2000-2031)")
    realisasi: Optional[str] = Field(
        None, max_length=100, description="Realisasi")
    nama_orang: Optional[str] = Field(
        None, max_length=255, description="Nama orang")
    keterangan: Optional[str] = Field(None, description="Keterangan/catatan")
    source_sheet_id: Optional[str] = Field(
        None, max_length=255, description="ID sheet sumber")
    source_sheet_name: Optional[str] = Field(
        None, max_length=255, description="Nama sheet sumber")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "nama_kpi": "KPI Penjualan",
            "tahun": 2026,
            "realisasi": "95%",
            "nama_orang": "John Doe",
            "keterangan": "Achieved target",
            "source_sheet_name": "Q1 Report"
        }
    })


class UpdateKPIRecordRequest(BaseModel):
    """Schema untuk update KPI record (semua field optional)."""
    nama_kpi: Optional[str] = Field(None, min_length=1, max_length=255)
    tahun: Optional[int] = Field(None, ge=2000, le=2031)
    realisasi: Optional[str] = Field(None, max_length=100)
    nama_orang: Optional[str] = Field(None, max_length=255)
    keterangan: Optional[str] = None
    source_sheet_id: Optional[str] = Field(None, max_length=255)
    source_sheet_name: Optional[str] = Field(None, max_length=255)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "realisasi": "98%",
            "keterangan": "Updated achievement"
        }
    })


class BulkCreateKPIRecordsRequest(BaseModel):
    """Schema untuk bulk create multiple KPI records."""
    records: List[CreateKPIRecordRequest] = Field(
        ..., min_length=1, max_length=10000)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "records": [
                {
                    "nama_kpi": "KPI A",
                    "tahun": 2026,
                    "realisasi": "90%"
                },
                {
                    "nama_kpi": "KPI B",
                    "tahun": 2026,
                    "realisasi": "85%"
                }
            ]
        }
    })


class BulkDeleteKPIRecordsRequest(BaseModel):
    """Schema untuk bulk delete multiple KPI records."""
    record_ids: List[UUID] = Field(..., min_length=1, max_length=1000)

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "record_ids": [
                "550e8400-e29b-41d4-a716-446655440000",
                "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
            ]
        }
    })


class IngestAllSheetsRequest(BaseModel):
    """Schema untuk ingest semua sheet dari satu spreadsheet."""
    sheet_url: str = Field(..., description="URL Google Sheets")
    tahun: int = Field(
        None, ge=2000, le=2031, description="Tahun data (opsional, fallback ke metadata sheet)")
    nama_orang_override: Optional[str] = Field(
        None, max_length=255,
        description="Override nama orang dari metadata sheet")
    skip_on_error: bool = Field(
        True, description="Skip sheet dengan error atau stop")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit",
            "tahun": 2026,
            "nama_orang_override": None,
            "skip_on_error": True,
        }
    })


# ================================================================ #
#  RESPONSE Schemas (Output Format)                                #
# ================================================================ #

class KPIRecordResponse(BaseModel):
    """Schema untuk single KPI record response."""
    id: UUID
    nama_kpi: str
    tahun: Optional[int]
    realisasi: Optional[str]
    nama_orang: Optional[str]
    keterangan: Optional[str]
    source_sheet_id: Optional[str]
    source_sheet_name: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginationInfo(BaseModel):
    """Schema untuk pagination metadata."""
    skip: int = Field(..., ge=0, description="Offset records")
    limit: int = Field(..., ge=1, le=500, description="Limit records per page")
    total: int = Field(..., ge=0, description="Total records")
    has_more: bool = Field(..., description="Ada records berikutnya")


class GroupInfo(BaseModel):
    """Schema untuk group info dalam grouped response."""
    nama_kpi: str
    total_count: int = Field(..., ge=0,
                             description="Total records dalam group")
    tahun_list: List[int] = Field(
        default_factory=list, description="List tahun")
    sheet_names: List[str] = Field(
        default_factory=list, description="List sheet names")
    sheet_count: int = Field(..., ge=0, description="Jumlah unique sheets")
    last_updated: Optional[datetime] = Field(
        None, description="Last update timestamp")


class GroupedKPIResponse(BaseModel):
    """Schema untuk grouped KPI records response."""
    groups: List[GroupInfo]
    pagination: PaginationInfo


class DetailRecordsResponse(BaseModel):
    """Schema untuk detail records (expand group) response."""
    nama_kpi: str = Field(..., description="Nama KPI yang di-expand")
    records: List[KPIRecordResponse]
    pagination: PaginationInfo


class BulkCreateResponse(BaseModel):
    """Schema untuk bulk create response."""
    status: str = Field(..., description="success/partial/failed")
    count: int = Field(..., ge=0, description="Jumlah records berhasil dibuat")
    message: str


class BulkDeleteResponse(BaseModel):
    """Schema untuk bulk delete response."""
    status: str = Field(..., description="success/partial/failed")
    count: int = Field(..., ge=0,
                       description="Jumlah records berhasil dihapus")
    message: str


class DeleteResponse(BaseModel):
    """Schema untuk delete single record response."""
    message: str


class CountResponse(BaseModel):
    """Schema untuk count response."""
    total: int = Field(..., ge=0, description="Total records")


class ListResponse(BaseModel):
    """Schema untuk list records response."""
    records: List[KPIRecordResponse]
    pagination: PaginationInfo


# ================================================================ #
#  Existing Schemas (untuk kompatibilitas)                         #
# ================================================================ #

class SheetMeta(BaseModel):
    nama_orang: Optional[str]
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
    log_id:     Optional[UUID] = None
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


# ================================================================ #
#  Batch Ingestion Schemas                                         #
# ================================================================ #

class TrackerSourceItem(BaseModel):
    """Satu item sumber dalam batch ingestion."""
    sheet_url: str = Field(..., description="URL Google Sheets")
    tahun: int = Field(
        None, ge=2000, le=2031, description="Tahun data")


class BatchTrackerIngestionRequest(BaseModel):
    """Request untuk batch ingest beberapa spreadsheet sekaligus."""
    sources: List[TrackerSourceItem] = Field(
        ..., min_length=1, max_length=6,
        description="List sumber (URL + tahun, max 6)",
    )
    sheet_urls: Optional[List[str]] = Field(
        default=None,
        description="Legacy input: list URL spreadsheet tanpa metadata tahun",
    )
    skip_on_error: bool = Field(
        True,
        description="Skip tab yang gagal atau batalkan per-spreadsheet",
    )
    delay_between_sources: float = Field(
        default=0.0,
        ge=0.0,
        description="Jeda (detik) antar ingest spreadsheet. Gunakan untuk menghindari rate limit Google Sheets API.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_sheet_urls(cls, values: Any):
        if not isinstance(values, dict):
            return values

        if values.get("sources"):
            return values

        sheet_urls = values.get("sheet_urls")
        if sheet_urls:
            values["sources"] = [
                {"sheet_url": sheet_url}
                for sheet_url in sheet_urls
            ]
        return values

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sources": [
                {"sheet_url": "https://docs.google.com/spreadsheets/d/abc/edit", "tahun": 2025},
                {"sheet_url": "https://docs.google.com/spreadsheets/d/xyz/edit", "tahun": 2026},
            ],
            "skip_on_error": True,
        }
    })


class UrlIngestionResult(BaseModel):
    """Hasil ingestion untuk satu URL dalam batch."""
    sheet_url: str
    status: str                           # success | partial | failed | error
    total_sheets_processed: int = 0
    grand_total_rows: int = 0
    grand_ingested: int = 0
    grand_failed: int = 0
    sheets: List[SheetIngestionResult] = Field(default_factory=list)
    error: Optional[str] = None           # diisi jika status = "error"


class BatchTrackerIngestionResponse(BaseModel):
    """Response untuk batch ingestion."""
    total_urls: int
    succeeded: int
    failed: int
    grand_total_rows: int = 0
    grand_ingested: int = 0
    grand_failed: int = 0
    results: List[UrlIngestionResult]
