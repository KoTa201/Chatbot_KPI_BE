"""
repository/schedulerRepository.py
"""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.SchedulerConfig import SchedulerConfigORM


class SchedulerRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self) -> Optional[SchedulerConfigORM]:
        result = await self.db.execute(select(SchedulerConfigORM).limit(1))
        return result.scalar_one_or_none()

    async def create_config(
        self,
        sheet_url: str,
        interval_value: int,
        interval_unit: str,
        is_enabled: bool,
    ) -> SchedulerConfigORM:
        config = SchedulerConfigORM(
            sheet_url=sheet_url,
            interval_value=interval_value,
            interval_unit=interval_unit,
            is_enabled=is_enabled,
        )
        self.db.add(config)
        try:
            await self.db.commit()
            await self.db.refresh(config)
            return config
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Gagal simpan scheduler config: {str(e)}")

    async def update_config(self, updates: dict) -> Optional[SchedulerConfigORM]:
        config = await self.get_config()
        if not config:
            return None
        for key, val in updates.items():
            if val is not None:
                setattr(config, key, val)
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def update_run_times(
        self,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
    ) -> None:
        config = await self.get_config()
        if not config:
            return
        if last_run_at:
            config.last_run_at = last_run_at
        if next_run_at:
            config.next_run_at = next_run_at
        await self.db.commit()
