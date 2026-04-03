"""
service/schedulerService.py
APScheduler AsyncIOScheduler lifecycle + job management.
"""

from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler(timezone="UTC")
JOB_ID = "kpi_tracker_ingestion"


def _build_trigger(interval_value: int, interval_unit: str) -> IntervalTrigger:
    if interval_unit == "months":
        return IntervalTrigger(days=interval_value * 30)
    return IntervalTrigger(**{interval_unit: interval_value})


async def _run_ingestion_job(sheet_url: str) -> None:
    """Executed by APScheduler on each interval tick."""
    from databaseConfig import AsyncSessionLocal
    from controller.ingestionController import IngestionController
    from repository.schedulerRepository import SchedulerRepository

    async with AsyncSessionLocal() as db:
        controller = IngestionController(db)
        await controller.ingest_all_sheets_from_google_sheets(
            sheet_url=sheet_url,
            nama_orang_override=None,
            skip_on_error=True,
        )

    # Update run timestamps
    async with AsyncSessionLocal() as db:
        repo = SchedulerRepository(db)
        job = scheduler.get_job(JOB_ID)
        next_run = job.next_run_time if job else None
        await repo.update_run_times(
            last_run_at=datetime.now(timezone.utc),
            next_run_at=next_run,
        )


async def register_job(config) -> None:
    """Add or replace the scheduler job from a SchedulerConfigORM instance."""
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)
    if not config.is_enabled:
        return
    trigger = _build_trigger(config.interval_value, config.interval_unit)
    scheduler.add_job(
        _run_ingestion_job,
        trigger=trigger,
        id=JOB_ID,
        args=[config.sheet_url],
        replace_existing=True,
        misfire_grace_time=300,
    )


def get_next_run_time() -> Optional[datetime]:
    job = scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
