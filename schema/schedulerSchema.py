from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID


class SchedulerConfigUpdate(BaseModel):
    interval_value: Optional[datetime] = None
    is_enabled: Optional[bool] = None

    @field_validator("interval_value")
    @classmethod
    def validate_day_and_hour(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is None:
            return v
        if not (1 <= v.day <= 28):
            raise ValueError("Day must be between 1 and 28")
        if not (0 <= v.hour <= 23):
            raise ValueError("Hour must be between 0 and 23")
        return v


class SchedulerConfigResponse(BaseModel):
    id: UUID
    interval_value: datetime
    is_enabled: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
