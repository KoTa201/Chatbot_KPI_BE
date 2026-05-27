from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from repository.schedulerRepository import SchedulerRepository
from model.SchedulerConfig import SchedulerConfigModel
from utils.datetime import utc_now


class SchedulerJobService:
    JOB_ID = "kpi_tracker_ingestion"
    TIMEZONE = "UTC"
    MISFIRE_GRACE_TIME = 300
    RATE_LIMIT_DELAY_SECONDS: float = 60.0

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=self.TIMEZONE)

    def _build_trigger(self, interval_value: datetime) -> CronTrigger:
        return CronTrigger(
            day=interval_value.day,
            hour=interval_value.hour,
            minute=0,
            timezone=self.TIMEZONE,
        )

    async def run_ingestion_job(self) -> None:
        """
        Executed by APScheduler on each cron tick.
        Opens its own sessions because it runs outside any request context.
        Processes each source one by one with a 60-second delay between them.
        """
        import asyncio
        from databaseConfig import AsyncSessionLocal
        from repository.KpiGroupRepository import KPIGroupRepository
        from service.TrackeringestionService import TrackerIngestionService

        async with AsyncSessionLocal() as db:
            group_repo = KPIGroupRepository(db)
            groups = await group_repo.get_active_scheduled_tracker()

        if not groups:
            return

        for i, group in enumerate(groups):
            if i > 0:
                await asyncio.sleep(self.RATE_LIMIT_DELAY_SECONDS)
            async with AsyncSessionLocal() as db:
                service = TrackerIngestionService(db=db)
                await service.ingest_all_sheets(
                    sheet_url=group.sheet_url,
                    tahun=group.tahun,
                    skip_on_error=True,
                )

        repo = SchedulerRepository()
        next_run = self.get_next_run_time()
        await repo.update_run_times(
            last_run_at=utc_now(),
            next_run_at=next_run,
        )

        await self._auto_pause_if_december()

    async def _auto_pause_if_december(self, now: Optional[datetime] = None) -> None:
        """Pause the scheduler after a December run (year-end cycle complete)."""
        if now is None:
            now = utc_now()
        if now.month != 12:
            return
        repo = SchedulerRepository()
        await repo.get_config()
        await repo.update_config({"is_enabled": False})
        if self.scheduler.get_job(self.JOB_ID):
            self.scheduler.remove_job(self.JOB_ID)

    def register_job(self, config: SchedulerConfigModel) -> None:
        if self.scheduler.get_job(self.JOB_ID):
            self.scheduler.remove_job(self.JOB_ID)
        if not config.is_enabled:
            return
        trigger = self._build_trigger(config.interval_value)
        self.scheduler.add_job(
            self.run_ingestion_job,
            trigger=trigger,
            id=self.JOB_ID,
            replace_existing=True,
            misfire_grace_time=self.MISFIRE_GRACE_TIME,
        )

    def get_next_run_time(self) -> Optional[datetime]:
        job = self.scheduler.get_job(self.JOB_ID)
        if not job:
            return None
        try:
            return job.trigger.get_next_fire_time(None, utc_now())
        except Exception:
            return None

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()


# Singleton — satu instance untuk seluruh umur aplikasi
scheduler_job_service = SchedulerJobService()
