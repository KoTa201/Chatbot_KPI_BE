"""
repository/schedulerRepository.py
"""
from datetime import datetime
from typing import Optional

from config.schedulerConfigManager import SchedulerConfigManager
from model.SchedulerConfig import SchedulerConfigModel


class SchedulerRepository:
    def __init__(self):
        self.config: Optional[SchedulerConfigModel] = None

    async def get_config(self) -> SchedulerConfigModel:
        self.config: Optional[SchedulerConfigModel] = await SchedulerConfigManager.get_config()
        return self.config

    async def update_config(self, updates: dict) -> SchedulerConfigModel:
        if not self.config:
            self.config: Optional[SchedulerConfigModel] = await self.get_config()

        # Update attributes
        for key, val in updates.items():
            if val is not None and hasattr(self.config, key):
                setattr(self.config, key, val)

        self.config.updated_at = datetime.now()
        await SchedulerConfigManager.save_config(self.config)
        return self.config

    async def update_run_times(
        self,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
    ) -> None:
        if not self.config:
            self.config: Optional[SchedulerConfigModel] = await self.get_config()

        if last_run_at:
            self.config.last_run_at = last_run_at
        if next_run_at:
            self.config.next_run_at = next_run_at

        await SchedulerConfigManager.save_config(self.config)
