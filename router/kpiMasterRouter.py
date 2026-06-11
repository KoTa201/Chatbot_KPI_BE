"""
router/kpiMasterRouter.py
Class-based router untuk KPI Master endpoints.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from databaseConfig import get_db
from schema.kpiMasterSchema import (
    IngestionResponse,
    IngestKPIMasterRequest,
)


class KPIMasterRouter:
    """Router untuk endpoints KPI Master."""

    def __init__(self):
        self.router: APIRouter = APIRouter()
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


# ─── Router instance ──────────────────────────────────────────────────────
router = KPIMasterRouter().router
