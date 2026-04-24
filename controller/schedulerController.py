"""
controller/schedulerController.py
"""
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.schedulerRepository import SchedulerRepository
from service.schedulerService import get_scheduler_service


class SchedulerController:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db
        self.repo: SchedulerRepository = SchedulerRepository(db)
        self.scheduler_service = get_scheduler_service()

    async def get_config(self) -> dict:
        config = await self.repo.get_config()
        if not config:
            return None
        return self._to_dict(config)

    async def create_config(
        self,
        interval_value: datetime,
        is_enabled: bool,
    ) -> dict:
        existing = await self.repo.get_config()
        if existing:
            raise HTTPException(
                status_code=409,
                detail="Config sudah ada. Gunakan PATCH untuk mengubah.",
            )
        config = await self.repo.create_config(
            interval_value=interval_value,
            is_enabled=is_enabled,
        )
        await self.scheduler_service.register_job(config)
        next_run = self.scheduler_service.get_next_run_time()
        await self.repo.update_run_times(next_run_at=next_run)
        config.next_run_at = next_run
        return self._to_dict(config)

    async def update_config(self, updates: dict) -> dict:
        config = await self.repo.update_config(
            {k: v for k, v in updates.items() if v is not None}
        )
        if not config:
            raise HTTPException(
                status_code=404, detail="Scheduler config belum dibuat."
            )
        await self.scheduler_service.register_job(config)
        next_run = self.scheduler_service.get_next_run_time()
        await self.repo.update_run_times(next_run_at=next_run)
        config.next_run_at = next_run
        return self._to_dict(config)

    async def trigger_now(self) -> dict:
        config = await self.repo.get_config()
        if not config:
            raise HTTPException(
                status_code=404, detail="Scheduler config belum dibuat."
            )
        await self.scheduler_service._run_ingestion_job()
        return {"message": "Ingestion triggered successfully."}

    @staticmethod
    def _to_dict(config) -> dict:
        return {
            "id":             str(config.id),
            "interval_value": config.interval_value,
            "is_enabled":     config.is_enabled,
            "last_run_at":    config.last_run_at,
            "next_run_at":    config.next_run_at,
        }
