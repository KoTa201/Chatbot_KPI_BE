"""
router/schedulerRouter.py
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from controller.schedulerController import SchedulerController
from databaseConfig import get_db
from schema.schedulerSchema import SchedulerConfigCreate, SchedulerConfigUpdate

router = APIRouter()


@router.get("", summary="Get scheduler config")
async def get_scheduler_config(db: AsyncSession = Depends(get_db)):
    controller = SchedulerController(db)
    return await controller.get_config()


@router.post("", summary="Create scheduler config")
async def create_scheduler_config(
    body: SchedulerConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    controller = SchedulerController(db)
    return await controller.create_config(
        sheet_url=body.sheet_url,
        interval_value=body.interval_value,
        interval_unit=body.interval_unit,
        is_enabled=body.is_enabled,
    )


@router.patch("", summary="Update scheduler config")
async def update_scheduler_config(
    body: SchedulerConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    controller = SchedulerController(db)
    return await controller.update_config(body.model_dump(exclude_unset=True))


@router.post("/trigger", summary="Manually trigger one ingestion run")
async def trigger_scheduler(db: AsyncSession = Depends(get_db)):
    controller = SchedulerController(db)
    return await controller.trigger_now()
