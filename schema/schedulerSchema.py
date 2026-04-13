from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SchedulerConfigCreate(BaseModel):
    sheet_urls: List[str] = Field(..., min_length=1, max_length=20)
    interval_value: int
    interval_unit: str   # hours / days / weeks / months
    is_enabled: bool = True


class SchedulerConfigUpdate(BaseModel):
    sheet_urls: Optional[List[str]] = Field(None, min_length=1, max_length=20)
    interval_value: Optional[int] = None
    interval_unit: Optional[str] = None
    is_enabled: Optional[bool] = None


class SchedulerConfigResponse(BaseModel):
    id: str
    sheet_urls: List[str]
    interval_value: int
    interval_unit: str
    is_enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True
