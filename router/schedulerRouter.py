"""
router/schedulerRouter.py
Class-based router untuk scheduler endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from controller.schedulerController import SchedulerController
from databaseConfig import get_db
from schema.schedulerSchema import SchedulerConfigCreate, SchedulerConfigUpdate


class SchedulerRouter:

    def __init__(self):
        self.router = APIRouter(tags=["Scheduler"])
        self.scheduler_controller = None
        self.setup_routes()

    def setup_routes(self):
        self.router.add_api_route(
            "", self.get_config, methods=["GET"], summary="Get scheduler config"
        )
        self.router.add_api_route(
            "", self.create_config, methods=["POST"], summary="Create scheduler config"
        )
        self.router.add_api_route(
            "", self.update_config, methods=["PATCH"], summary="Update scheduler config"
        )
        self.router.add_api_route(
            "/trigger", self.trigger_scheduler,
            methods=["POST"], summary="Manually trigger one ingestion run"
        )

    async def get_config(self, db: AsyncSession = Depends(get_db)):
        self.scheduler_controller = SchedulerController(db)
        return await self.scheduler_controller.get_config()

    async def create_config(
        self, body: SchedulerConfigCreate, db: AsyncSession = Depends(get_db)
    ):
        self.scheduler_controller = SchedulerController(db)
        return await self.scheduler_controller.create_config(
            interval_value=body.interval_value,
            is_enabled=body.is_enabled,
        )

    async def update_config(
        self, body: SchedulerConfigUpdate, db: AsyncSession = Depends(get_db)
    ):
        self.scheduler_controller = SchedulerController(db)
        return await self.scheduler_controller.update_config(
            body.model_dump(exclude_unset=True)
        )

    async def trigger_scheduler(self, db: AsyncSession = Depends(get_db)):
        self.scheduler_controller = SchedulerController(db)
        return await self.scheduler_controller.trigger_now()


# ─── Router instance ─────────────────────────────────────────────────────
router = SchedulerRouter().router
