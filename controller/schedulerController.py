"""
controller/schedulerController.py
"""


from schema.schedulerSchema import (
    SchedulerConfigResponse,
    SchedulerConfigUpdate,
)
from service.schedulerService import SchedulerService


class SchedulerController:

    def __init__(self):
        self.service: SchedulerService = SchedulerService()

    async def get_config(self) -> SchedulerConfigResponse:
        config = await self.service.get_config()
        return SchedulerConfigResponse.model_validate(config)

    async def update_config(
        self,
        payload: SchedulerConfigUpdate,
    ) -> SchedulerConfigResponse:
        config = await self.service.update_config(payload.model_dump(exclude_none=True))
        return SchedulerConfigResponse.model_validate(config)

    async def trigger_now(self) -> dict:
        await self.service.trigger_now()
        return {"message": "Ingestion triggered successfully."}
