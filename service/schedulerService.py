"""
service/schedulerService.py

Business layer untuk scheduler config.
Config selalu tersedia (default JSON), tidak ada proses create.
"""
from repository.schedulerRepository import SchedulerRepository
from service.schedulerJobService import SchedulerJobService, scheduler_job_service


class SchedulerService:
    """
    Owns all scheduler business logic.
    Coordinates the repository (data) and SchedulerJobService (APScheduler).
    """

    def __init__(self):
        self.repo: SchedulerRepository = SchedulerRepository()
        self.job_service: SchedulerJobService = scheduler_job_service

    async def get_config(self):
        return await self.repo.get_config()

    async def update_config(self, updates: dict):
        config = await self.repo.update_config(
            {k: v for k, v in updates.items() if v is not None}
        )
        self.job_service.register_job(config)
        next_run = self.job_service.get_next_run_time()
        await self.repo.update_run_times(next_run_at=next_run)
        config.next_run_at = next_run
        return config

    async def trigger_now(self) -> None:
        """Manually fire the ingestion job outside the cron schedule."""
        await self.job_service.run_ingestion_job()
