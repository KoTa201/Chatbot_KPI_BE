from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class SchedulerConfigCreate(BaseModel):
    sheet_url: str
    interval_value: int
    interval_unit: str   # hours / days / weeks / months
    is_enabled: bool = True


class SchedulerConfigUpdate(BaseModel):
    sheet_url: Optional[str] = None
    interval_value: Optional[int] = None
    interval_unit: Optional[str] = None
    is_enabled: Optional[bool] = None


class SchedulerConfigResponse(BaseModel):
    id: str
    sheet_url: str
    interval_value: int
    interval_unit: str
    is_enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    class Config:
        from_attributes = True
