"""
schema/kpiGroupSchema.py

Pydantic schemas untuk KPI Group endpoints.

Catatan penamaan nested response:
  Kelas nested di file ini sengaja diberi prefix 'KPIGroup' —
  KPIGroupMasterRecord dan KPIGroupTrackerRecord — untuk menghindari
  collision dengan KPIMasterResponse / KPIRecordResponse yang mungkin
  sudah ada di kpiMasterSchema.py atau kpiTrackerSchema.py lain.

  Kedua kelas ini hanya dipakai di dalam KPIGroupResponse dan
  tidak dimaksudkan untuk menggantikan schema di file lain.

Penyesuaian field terhadap ORM saat ini:
  KPIGroupMasterRecord  (≈ KPIMaster):
    - TIDAK ADA: source_sheet_id, source_sheet_name  → ada di KPIGroupResponse
    - TIDAK ADA: updated_at                          → kolom tidak ada di ORM
    - ADA:       group_id                            → FK yang ada di ORM

  KPIGroupTrackerRecord (≈ KPITracker):
    - TIDAK ADA: nama_kpi                            → kolom dihapus dari ORM
    - TIDAK ADA: source_sheet_id, source_sheet_name  → ada di KPIGroupResponse
    - ADA:       group_id, kpi_master_id             → FK yang ada di ORM
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID
from enum import Enum
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


# ─── Konstanta group_type ─────────────────────────────────────────────────────
GROUP_TYPE_MASTER = "master"
GROUP_TYPE_TRACKER = "tracker"
VALID_GROUP_TYPES = {GROUP_TYPE_MASTER, GROUP_TYPE_TRACKER}


class GroupTypeEnum(str, Enum):
    master = "master"
    tracker = "tracker"


class PICUserResponse(BaseModel):
    id:        UUID
    full_name: str

    model_config = {"from_attributes": True}



# ─── Nested: KPI Master record (bersarang di dalam KPIGroupResponse) ──────────
class KPIGroupMasterRecord(BaseModel):
    id:                    UUID
    group_id:              UUID
    tahun:                 int
    category:              str
    kpi_name:              str
    definisi_operasional:  Optional[str] = None
    target:                Optional[str] = None
    achieve:               Optional[str] = None
    partial:               Optional[str] = None
    fail:                  Optional[str] = None
    # ORM attr: pic_users → response key: responsibility_persons
    responsibility_persons: list[PICUserResponse] = Field(
        default=[], validation_alias="pic_users"
    )
    created_at:            datetime

    model_config = {"from_attributes": True}


class KPIGroupTrackerRecord(BaseModel):
    id:            UUID
    group_id:      UUID
    kpi_master_id: Optional[UUID] = None
    tahun:         int
    bulan_num:     Optional[int] = None
    realisasi:     Optional[str] = None
    keterangan:    Optional[str] = None
    # ORM attr: user → response key: responsibility_person
    responsibility_person: Optional[PICUserResponse] = Field(
        default=None, validation_alias="user"
    )
    created_at:    datetime
    updated_at:    datetime

    model_config = {"from_attributes": True}


# ─── Base ─────────────────────────────────────────────────────────────────────
class KPIGroupBase(BaseModel):
    group_type: str = Field(..., description="'master' atau 'tracker'")
    sheet_url:  AnyHttpUrl = Field(..., description="URL Google Sheets sumber")
    # nama_grup opsional — di-fetch otomatis dari Google Sheets jika tidak disertakan
    nama_grup:  Optional[str] = Field(None, max_length=255)
    sheet_id:   Optional[str] = Field(None, max_length=255)
    sheet_name: Optional[str] = Field(None, max_length=255)

    @model_validator(mode="after")
    def validate_group_type(self) -> "KPIGroupBase":
        if self.group_type not in VALID_GROUP_TYPES:
            raise ValueError(
                f"group_type harus salah satu dari: {sorted(VALID_GROUP_TYPES)}"
            )
        return self


# ─── Create ───────────────────────────────────────────────────────────────────
class KPIGroupCreate(KPIGroupBase):
    # Kolom khusus tracker
    tahun:     Optional[int] = Field(None, ge=2000, le=2100)
    is_active: bool = Field(True)


# ─── Update ───────────────────────────────────────────────────────────────────
class KPIGroupUpdate(BaseModel):
    """
    Partial update. Jika sheet_url berubah → service jalankan ulang ingestion.
    Untuk grup 'master', `tahun` wajib disertakan jika sheet_url diubah.
    """
    nama_grup:    Optional[str] = Field(None, max_length=255)
    sheet_url:    Optional[AnyHttpUrl] = Field(None)
    sheet_id:     Optional[str] = Field(None, max_length=255)
    sheet_name:   Optional[str] = Field(None, max_length=255)
    tahun:     Optional[int] = Field(None, ge=2000, le=2100)
    is_active: Optional[bool] = None


# ─── Response ─────────────────────────────────────────────────────────────────
class KPIGroupResponse(BaseModel):
    """
    Response lengkap satu KPI Group.

    Hanya satu list yang terisi sesuai group_type:
      'master'  → master_records  terisi, tracker_records  = []
      'tracker' → tracker_records terisi, master_records   = []
    """
    id:              UUID
    nama_grup:       str
    group_type:      str
    sheet_url:       AnyHttpUrl
    sheet_id:        Optional[str] = None
    sheet_name:      Optional[str] = None
    tahun:     Optional[int] = None
    is_active: bool = True
    created_at:      datetime
    updated_at:      datetime
    master_records:  list[KPIGroupMasterRecord] = Field(default_factory=list)
    tracker_records: list[KPIGroupTrackerRecord] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ─── List (pagination) ────────────────────────────────────────────────────────
class KPIGroupListResponse(BaseModel):
    """List endpoint tidak menyertakan records — hanya metadata grup."""
    total:       int
    page:        int
    limit:       int
    total_pages: int
    data:        list[KPIGroupResponse]


# ─── Generic message ──────────────────────────────────────────────────────────
class MessageResponse(BaseModel):
    message: str
