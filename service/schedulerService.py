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
    Mengelola KPI Tracker ingestion job dengan interval yang dapat dikonfigurasi.
    """

    JOB_ID = "kpi_tracker_ingestion"
    TIMEZONE = "UTC"
    MISFIRE_GRACE_TIME = 300

    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=self.TIMEZONE)

    def _build_trigger(self, interval_value: int, interval_unit: str) -> IntervalTrigger:
        """Bangun trigger berdasarkan interval_value dan interval_unit."""
        if interval_unit == "months":
            return IntervalTrigger(days=interval_value * 30)
        return IntervalTrigger(**{interval_unit: interval_value})

    async def _run_ingestion_job(self, sheet_url: str) -> None:
        """Dieksekusi oleh APScheduler pada setiap interval tick."""
        from databaseConfig import AsyncSessionLocal
        from controller.kpiTrackerController import kpiTrackerController
        from repository.schedulerRepository import SchedulerRepository

        async with AsyncSessionLocal() as db:
            controller = kpiTrackerController(db)
            await controller.ingest_all_sheets_from_google_sheets(
                sheet_url=sheet_url,
                nama_orang_override=None,
                skip_on_error=True,
            )

        # Update run timestamps
        async with AsyncSessionLocal() as db:
            repo = SchedulerRepository(db)
            job = self.scheduler.get_job(self.JOB_ID)
            # Get next run time from trigger if job exists
            next_run = None
            if job and hasattr(job, 'trigger'):
                try:
                    next_run = job.trigger.get_next_fire_time(
                        None, datetime.now(timezone.utc))
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
            args=[config.sheet_url],
            replace_existing=True,
            misfire_grace_time=self.MISFIRE_GRACE_TIME,
        )

    def get_next_run_time(self) -> Optional[datetime]:
        """Dapatkan waktu eksekusi job berikutnya."""
        job = self.scheduler.get_job(self.JOB_ID)
        if not job:
            return None
        # Get next run time from trigger
        if hasattr(job, 'trigger'):
            try:
                return job.trigger.get_next_fire_time(None, datetime.now(timezone.utc))
            except Exception:
                return None
        return None

    def start_scheduler(self) -> None:
        """Mulai scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()

    def stop_scheduler(self) -> None:
        """Hentikan scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()


# ─── Global singleton instance untuk backward compatibility ─────────────────── #
_scheduler_instance = SchedulerService()

# Wrapper functions untuk backward compatibility


async def register_job(config) -> None:
    """Backward compatibility wrapper."""
    await _scheduler_instance.register_job(config)


def get_next_run_time() -> Optional[datetime]:
    """Backward compatibility wrapper."""
    return _scheduler_instance.get_next_run_time()


def get_scheduler_service() -> SchedulerService:
    """Dapatkan scheduler service instance."""
    return _scheduler_instance
