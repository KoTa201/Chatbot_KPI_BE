from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TrackerSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    sheet_url: str = Field(..., min_length=1)
    is_scheduled: bool = True


class TrackerSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    sheet_url: Optional[str] = Field(None, min_length=1)
    is_active: Optional[bool] = None
    is_scheduled: Optional[bool] = None


class TrackerSourceResponse(BaseModel):
    id: str
    name: str
    sheet_url: str
    is_active: bool
    is_scheduled: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
