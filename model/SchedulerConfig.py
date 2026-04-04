# ------------------------------------------------------------------ #
#  Tabel: scheduler_configs                                            #
# ------------------------------------------------------------------ #
from datetime import datetime
from typing import Optional
from uuid import uuid4
from sqlalchemy import UUID, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from databaseConfig import Base


class SchedulerConfigORM(Base):
    __tablename__ = "scheduler_configs"

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True, index=True, default=uuid4)
    sheet_url: Mapped[str] = mapped_column(Text, nullable=False)
    interval_value: Mapped[int] = mapped_column(Integer, nullable=False)
    interval_unit: Mapped[str] = mapped_column(String(20), nullable=False)  # hours/days/weeks/months
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True)  # NULL until first update
