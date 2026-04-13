"""
model/TrackerSource.py
Registry of Google Sheets URLs to be ingested by the scheduler.
Each row represents one spreadsheet source that the user manages.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy import UUID as SAUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from databaseConfig import Base


class TrackerSourceORM(Base):
    __tablename__ = "tracker_sources"

    id: Mapped[SAUUID] = mapped_column(
        SAUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_scheduled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TrackerSource id={self.id} name='{self.name}'>"
