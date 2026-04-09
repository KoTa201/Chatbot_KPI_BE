"""
router/kpiMasterRouter.py
Class-based router untuk KPI Master ingestion endpoints.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiMasterController import KPIMasterController
from databaseConfig import get_db
from schema.kpiMasterSchema import KPIMasterIngestionResponse


class KPIMasterRouter:
    """Router untuk endpoints KPI Master ingestion."""

    def __init__(self):
        self.router = APIRouter(prefix="/kpi-master", tags=["KPI Master"])
        self.kpi_master_controller: KPIMasterController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register all KPI Master routes."""
        self.router.add_api_route("", self.ingest_kpi_master, methods=[
                                  "POST"], response_model=KPIMasterIngestionResponse, summary="Ingest KPI Master dari Google Sheets")
        self.router.add_api_route("/preview", self.preview_kpi_master,
                                  methods=["GET"], summary="Preview KPI Master tanpa simpan")

    async def ingest_kpi_master(
        self,
        sheet_url: str = Query(...,
                               description="URL Google Sheets KPI Master"),
        tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
        db: AsyncSession = Depends(get_db),
    ):
        self.kpi_master_controller = KPIMasterController(db)
        return await self.kpi_master_controller.ingest_kpi_master(sheet_url, tahun=tahun)

    async def preview_kpi_master(
        self,
        sheet_url: str = Query(...),
        tahun: int = Query(..., description="Tahun KPI Master, contoh: 2024"),
        db: AsyncSession = Depends(get_db),
    ):
        self.kpi_master_controller = KPIMasterController(db)
        return await self.kpi_master_controller.preview_kpi_master(sheet_url, tahun=tahun)


# ─── Router instance ─────────────────────────────────────────────────────
router = KPIMasterRouter().router
