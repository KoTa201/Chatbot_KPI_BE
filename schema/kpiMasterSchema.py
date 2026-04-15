"""
schemas/kpiMasterSchema.py
Pydantic models untuk request/response endpoint KPI Master management.
"""

from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


# ================================================================ #
#  REQUEST Schemas (Input Validation)                              #
# ================================================================ #

class IngestKPIMasterRequest(BaseModel):
    """Schema untuk ingest KPI Master dari Google Sheets."""
    sheet_url: str = Field(..., description="URL Google Sheets")
    tahun: int = Field(..., ge=2000, le=2031, description="Tahun (2000-2031)")

    class Config:
        example = {
            "sheet_url": "https://docs.google.com/spreadsheets/d/abc123/edit",
            "tahun": 2026
        }


# ================================================================ #
#  RESPONSE Schemas (Output Format)                                #
# ================================================================ #

class KPIMasterResponse(BaseModel):
    """Schema untuk single KPI Master response."""
    id: UUID
    tahun: int
    category: str
    kpi_name: str
    definisi_operasional: Optional[str]
    target: Optional[str]
    achieve: Optional[str]
    partial: Optional[str]
    fail: Optional[str]
    responsibility_persons: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class PaginationInfo(BaseModel):
    """Schema untuk pagination metadata."""
    skip: int = Field(..., ge=0, description="Offset records")
    limit: int = Field(..., ge=1, le=500, description="Limit records per page")
    total: int = Field(..., ge=0, description="Total records")
    has_more: bool = Field(..., description="Ada records berikutnya")


class GroupInfo(BaseModel):
    """Schema untuk group info dalam grouped response."""
    source_sheet_name: str
    total_count: int = Field(..., ge=0,
                             description="Total records dalam group")
    tahun_list: List[int] = Field(
        default_factory=list, description="List tahun")
    categories: List[str] = Field(
        default_factory=list, description="List categories")
    kpi_count: int = Field(..., ge=0, description="Jumlah unique KPI names")
    last_updated: Optional[datetime] = Field(
        None, description="Last update timestamp")


class GroupedKPIMasterResponse(BaseModel):
    """Schema untuk grouped KPI Masters response."""
    groups: List[GroupInfo]
    pagination: PaginationInfo


class DetailMastersResponse(BaseModel):
    """Schema untuk detail masters (expand group) response."""
    source_sheet_name: str = Field(..., description="Nama file yang di-expand")
    records: List[KPIMasterResponse]
    pagination: PaginationInfo


class IngestionResponse(BaseModel):
    """Schema untuk ingestion response."""
    status: str = Field(..., description="success/partial/failed")
    count: int = Field(..., ge=0,
                       description="Jumlah records berhasil di-ingest")
    message: str


class DeleteMastersResponse(BaseModel):
    """Schema untuk delete response."""
    status: str = Field(..., description="success/partial/failed")
    count: int = Field(..., ge=0,
                       description="Jumlah records berhasil dihapus")
    message: str


# ================================================================ #
#  Legacy Schemas (untuk kompatibilitas)                           #
# ================================================================ #

class KPIMasterIngestionResponse(BaseModel):
    sheet_id: str
    sheet_name: str
    tahun: int
    total_rows: int
    ingested: int
    failed: int
    errors: List[str]
    status: str
