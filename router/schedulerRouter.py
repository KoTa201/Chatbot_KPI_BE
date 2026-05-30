"""
router/schedulerRouter.py
Class-based router untuk scheduler endpoints.
"""

from fastapi import APIRouter

from controller.schedulerController import SchedulerController
from schema.schedulerSchema import SchedulerConfigUpdate


class SchedulerRouter:
    """Router untuk endpoints scheduler configuration."""

    def __init__(self):
        self.router = APIRouter(tags=["Scheduler"])
        self.scheduler_controller: SchedulerController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register all scheduler routes."""
        self.router.add_api_route("", self.get_config, methods=[
                                  "GET"], summary="Get scheduler config")
        self.router.add_api_route("", self.update_config, methods=[
                                  "PATCH"], summary="Update scheduler config")
        self.router.add_api_route("/trigger", self.trigger_scheduler,
                                  methods=["POST"], summary="Manually trigger one ingestion run")

    async def get_config(self):
        """Get current scheduler configuration."""
        self.scheduler_controller = SchedulerController()
        return await self.scheduler_controller.get_config()

    async def update_config(self, body: SchedulerConfigUpdate):
        """Update existing scheduler configuration."""
        self.scheduler_controller = SchedulerController()
        return await self.scheduler_controller.update_config(payload=body)

    async def trigger_scheduler(self):
        """Manually trigger ingestion job."""
        self.scheduler_controller = SchedulerController()
        return await self.scheduler_controller.trigger_now()


# ─── Router instance ─────────────────────────────────────────────────────
router = SchedulerRouter().router
