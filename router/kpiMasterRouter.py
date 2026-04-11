"""
router/kpiMasterRouter.py
Class-based router untuk KPI Master endpoints.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from databaseConfig import get_db
from schema.kpiMasterSchema import (
    DetailMastersResponse,
    GroupedKPIMasterResponse,
    IngestionResponse,
    IngestKPIMasterRequest,
    DeleteMastersResponse
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
            "/ingest",
            self.ingest_kpi_master,
            methods=["POST"],
            response_model=IngestionResponse,
            summary="Ingest KPI Master dari Google Sheets",
        )
        self.router.add_api_route(
            "/ingest/preview",
            self.preview_kpi_master,
            methods=["GET"],
            summary="Preview KPI Master tanpa simpan",
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
            "/grouped/filter",
            self.get_grouped_records_with_filters,
            methods=["GET"],
            response_model=GroupedKPIMasterResponse,
            summary="KPI Masters grouped dengan filter tahun/category",
        )
        self.router.add_api_route(
            "/grouped/{source_sheet_name}",
            self.get_detail_records_by_source_sheet_name,
            methods=["GET"],
            response_model=DetailMastersResponse,
            summary="Detail records untuk satu source_sheet_name (expand group)",
        )

        # ── DELETE ─────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/grouped/{source_sheet_name}",
            self.delete_records_by_source_sheet_name,
            methods=["DELETE"],
            response_model=DeleteMastersResponse,
            summary="Hapus semua records untuk satu source_sheet_name",
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

    async def preview_kpi_master(
        self,
        sheet_url: str = Query(...,
                               description="URL Google Sheets KPI Master"),
        tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).preview_kpi_master(sheet_url, tahun)

    # ── GROUP / READ handlers ──────────────────────────────────────── #

    async def get_grouped_records(
        self,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_grouped_records(skip=skip, limit=limit)

    async def get_grouped_records_with_filters(
        self,
        tahun: Optional[int] = Query(default=None),
        category: Optional[str] = Query(default=None),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_grouped_records_with_filters(
            tahun=tahun, category=category, skip=skip, limit=limit
        )

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

    async def delete_records_by_source_sheet_name(
        self,
        source_sheet_name: str,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).delete_records_by_source_sheet_name(
            source_sheet_name
        )


# ─── Router instance ──────────────────────────────────────────────────────
router = KPIMasterRouter().router
