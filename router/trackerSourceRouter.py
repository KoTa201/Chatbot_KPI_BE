"""
router/trackerSourceRouter.py
Class-based router for tracker source CRUD endpoints.
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from controller.trackerSourceController import TrackerSourceController
from databaseConfig import get_db
from schema.trackerSourceSchema import (
    TrackerSourceCreate,
    TrackerSourceResponse,
    TrackerSourceUpdate,
)


class TrackerSourceRouter:

    def __init__(self):
        self.router = APIRouter(tags=["Tracker Sources"])
        self.setup_routes()

    def setup_routes(self):
        self.router.add_api_route(
            "",
            self.list_sources,
            methods=["GET"],
            response_model=list[TrackerSourceResponse],
            summary="List all tracker sources",
        )
        self.router.add_api_route(
            "",
            self.create_source,
            methods=["POST"],
            response_model=TrackerSourceResponse,
            status_code=201,
            summary="Create tracker source",
        )
        self.router.add_api_route(
            "/{source_id}",
            self.update_source,
            methods=["PATCH"],
            response_model=TrackerSourceResponse,
            summary="Update tracker source",
        )
        self.router.add_api_route(
            "/{source_id}",
            self.delete_source,
            methods=["DELETE"],
            response_model=dict,
            summary="Delete tracker source",
        )

    async def list_sources(self, db: AsyncSession = Depends(get_db)):
        return await TrackerSourceController(db).get_all()

    async def create_source(
        self, body: TrackerSourceCreate, db: AsyncSession = Depends(get_db)
    ):
        return await TrackerSourceController(db).create(
            name=body.name,
            sheet_url=body.sheet_url,
            is_scheduled=body.is_scheduled,
        )

    async def update_source(
        self,
        source_id: UUID,
        body: TrackerSourceUpdate,
        db: AsyncSession = Depends(get_db),
    ):
        return await TrackerSourceController(db).update(
            source_id, body.model_dump(exclude_unset=True)
        )

    async def delete_source(
        self, source_id: UUID, db: AsyncSession = Depends(get_db)
    ):
        return await TrackerSourceController(db).delete(source_id)


# ─── Router instance ──────────────────────────────────────────────────────
router = TrackerSourceRouter().router
