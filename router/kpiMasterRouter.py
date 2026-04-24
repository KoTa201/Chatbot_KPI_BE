"""
router/kpiMasterRouter.py
Class-based router untuk KPI Master endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from databaseConfig import get_db
from schema.kpiGroupSchema import KPIGroupListResponse, KPIGroupUpdate
from schema.kpiMasterSchema import (
    DetailMastersResponse,
    GroupedKPIMasterResponse,
    IngestionResponse,
    IngestKPIMasterRequest,
)


class KPIMasterRouter:
    """Router untuk endpoints KPI Master."""

    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def _get_controller(self, db: AsyncSession) -> KPIMasterController:
        return KPIMasterController(db)

    def setup_routes(self):
        """Register all KPI Master routes."""

        # ── Ingestion ──────────────────────────────────────────────── #
        self.router.add_api_route(
            "",
            self.ingest_kpi_master,
            methods=["POST"],
            response_model=IngestionResponse,
            summary="Ingest KPI Master dari Google Sheets",
        )
        self.router.add_api_route(
            "/management",
            self.list_master_groups,
            methods=["GET"],
            response_model=KPIGroupListResponse,
            summary="List KPI Master groups untuk management",
        )
        self.router.add_api_route(
            "/management/{group_id}",
            self.update_and_reingest,
            methods=["PUT"],
            response_model=IngestionResponse,
            summary="Update KPI Master group dan re-ingest data",
        )

        # ── READ / GROUP ───────────────────────────────────────────── #
        self.router.add_api_route(
            "/grouped",
            self.get_grouped_records,
            methods=["GET"],
            response_model=GroupedKPIMasterResponse,
            summary="KPI Masters dikelompokkan berdasarkan source_sheet_name",
        )
        self.router.add_api_route(
            "/grouped/{source_sheet_name}",
            self.get_detail_records_by_source_sheet_name,
            methods=["GET"],
            response_model=DetailMastersResponse,
            summary="Detail records untuk satu source_sheet_name (expand group)",
        )

    # ── Ingestion handlers ─────────────────────────────────────────── #

    async def ingest_kpi_master(
        self,
        sheet_url: str = Query(...,
                               description="URL Google Sheets KPI Master"),
        tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
        db: AsyncSession = Depends(get_db),
    ):
        request = IngestKPIMasterRequest(sheet_url=sheet_url, tahun=tahun)
        return await self._get_controller(db).ingest_kpi_master(request)

    async def list_master_groups(
        self,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=100),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).list_master_groups(
            page=page,
            page_size=page_size,
        )

    async def update_and_reingest(
        self,
        group_id: UUID,
        payload: KPIGroupUpdate = Body(...),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).update_and_reingest(
            group_id=group_id,
            payload=payload,
        )

    # ── GROUP / READ handlers ──────────────────────────────────────── #

    async def get_grouped_records(
        self,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_grouped_records(skip=skip, limit=limit)

    async def get_detail_records_by_source_sheet_name(
        self,
        source_sheet_name: str,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_detail_records_by_source_sheet_name(
            source_sheet_name, skip, limit
        )


# ─── Router instance ──────────────────────────────────────────────────────
router = KPIMasterRouter().router
