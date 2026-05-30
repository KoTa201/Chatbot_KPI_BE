"""
model/SchedulerConfig.py

Konfigurasi scheduler untuk proses ingestion otomatis.
Kini disimpan menggunakan Pydantic model dan file JSON.
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4, UUID

from pydantic import BaseModel, Field


class SchedulerConfigModel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    interval_value: datetime
    is_enabled: bool = True
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def __repr__(self) -> str:
        return f"<SchedulerConfig id={self.id} enabled={self.is_enabled}>"
