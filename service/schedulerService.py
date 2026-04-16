"""
service/schedulerService.py
APScheduler AsyncIOScheduler lifecycle + job management.
"""
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger


class SchedulerService:
    """
    Service untuk mengelola APScheduler lifecycle dan job scheduling.
    Saat job fire, query tracker_sources untuk mendapatkan URLs aktif+terjadwal.
    """

    JOB_ID = "kpi_tracker_ingestion"
    TIMEZONE = "UTC"
    MISFIRE_GRACE_TIME = 300

    def __init__(self):
        self.scheduler: AsyncIOScheduler = AsyncIOScheduler(
            timezone=self.TIMEZONE)

    def _build_trigger(self, interval_value: int, interval_unit: str) -> IntervalTrigger:
        if interval_unit == "months":
            return IntervalTrigger(days=interval_value * 30)
        return IntervalTrigger(**{interval_unit: interval_value})

    async def _run_ingestion_job(self) -> None:
        """Dieksekusi oleh APScheduler pada setiap interval tick.
        Query tracker_sources aktif+terjadwal lalu jalankan batch ingestion."""
        from databaseConfig import AsyncSessionLocal
        from controller.kpiTrackerController import KPITrackerController
        from repository.schedulerRepository import SchedulerRepository
        from repository.kpiGroupRepository import KPIGroupRepository
        from schema.kpiTrackerSchema import BatchTrackerIngestionRequest

        async with AsyncSessionLocal() as db:
            group_repo = KPIGroupRepository(db)
            groups = await group_repo.get_active_scheduled_tracker()
            source_items = [
                {"sheet_url": g.sheet_url, "tahun": g.tahun}
                for g in groups
            ]

        if not source_items:
            return

        async with AsyncSessionLocal() as db:
            controller = KPITrackerController(db)
            request = BatchTrackerIngestionRequest(
                sources=source_items,
                skip_on_error=True,
            )
            await controller.ingest_batch_from_google_sheets(request)

        # Update run timestamps
        async with AsyncSessionLocal() as db:
            repo = SchedulerRepository(db)
            job = self.scheduler.get_job(self.JOB_ID)
            next_run = None
            if job and hasattr(job, "trigger"):
                try:
                    next_run = job.trigger.get_next_fire_time(
                        None, datetime.now(timezone.utc)
                    )
                except Exception:
                    next_run = None
            await repo.update_run_times(
                last_run_at=datetime.now(timezone.utc),
                next_run_at=next_run,
            )

    async def register_job(self, config) -> None:
        """Tambah atau replace scheduler job dari SchedulerConfigORM instance."""
        if self.scheduler.get_job(self.JOB_ID):
            self.scheduler.remove_job(self.JOB_ID)
        if not config.is_enabled:
            return
        trigger = self._build_trigger(
            config.interval_value, config.interval_unit)
        self.scheduler.add_job(
            self._run_ingestion_job,
            trigger=trigger,
            id=self.JOB_ID,
            replace_existing=True,
            misfire_grace_time=self.MISFIRE_GRACE_TIME,
        )

    def get_next_run_time(self) -> Optional[datetime]:
        job = self.scheduler.get_job(self.JOB_ID)
        if not job:
            return None
        if hasattr(job, "trigger"):
            try:
                return job.trigger.get_next_fire_time(None, datetime.now(timezone.utc))
            except Exception:
                return None
        return None

    def start_scheduler(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()

    def stop_scheduler(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown()


# ─── Global singleton instance ──────────────────────────────────────────── #
_scheduler_instance = SchedulerService()


async def register_job(config) -> None:
    await _scheduler_instance.register_job(config)


def get_next_run_time() -> Optional[datetime]:
    return _scheduler_instance.get_next_run_time()


def get_scheduler_service() -> SchedulerService:
    return _scheduler_instance
