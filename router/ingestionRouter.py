"""
router/ingestionRouter.py
Class-based router untuk ingestion endpoints.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiTrackerController import kpiTrackerController
from databaseConfig import get_db
from schema.ingestionSchema import BulkIngestionResponse, SheetIngestionResult


class IngestionRouter:
    """Router untuk endpoints ingestion data KPI."""

    def __init__(self):
        self.router = APIRouter(prefix="/ingestion", tags=["Ingestion"])
        self.ingestion_controller: kpiTrackerController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register all ingestion routes."""
        self.router.add_api_route("/google-sheets", self.ingest_from_google_sheets, methods=[
                                  "POST"], response_model=BulkIngestionResponse, summary="Ingest KPI dari Google Sheets")
        self.router.add_api_route("/sheets/tabs", self.list_sheet_tabs,
                                  methods=["GET"], summary="List semua tab dalam spreadsheet")
        self.router.add_api_route(
            "/sheets/preview", self.preview_sheet, methods=["GET"], summary="Preview sheet")
        self.router.add_api_route(
            "/logs", self.get_ingestion_logs, methods=["GET"], summary="Riwayat ingestion")

    async def ingest_from_google_sheets(
        self,
        sheet_url: str = Query(..., description="URL Google Sheets"),
        nama_orang_override: Optional[str] = Query(
            default=None, description="Override nama orang jika tidak bisa diekstrak"),
        skip_on_error: bool = Query(
            default=False, description="Lewati sheet yang gagal atau batalkan seluruh proses"),
        db: AsyncSession = Depends(get_db),
    ):
        self.ingestion_controller = kpiTrackerController(db)
        return await self.ingestion_controller.ingest_all_sheets_from_google_sheets(
            sheet_url=sheet_url,
            nama_orang_override=nama_orang_override,
            skip_on_error=skip_on_error,
        )

    async def list_sheet_tabs(self, sheet_url: str = Query(..., description="URL Google Sheets")):
        self.ingestion_controller = kpiTrackerController()
        return await self.ingestion_controller.list_sheet_tabs(sheet_url=sheet_url)

    async def preview_sheet(
        self,
        sheet_url: str = Query(...),
        sheet_name: Optional[str] = Query(default=None),
        sheet_index: int = Query(default=0),
    ):
        self.ingestion_controller = kpiTrackerController()
        return await self.ingestion_controller.preview_sheet(
            sheet_url=sheet_url,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
        )

    async def get_ingestion_logs(
        self,
        limit: int = Query(default=20, le=100),
        source_type: Optional[Literal["kpi_tracker",
                                      "kpi_master"]] = Query(default=None),
        db: AsyncSession = Depends(get_db),
    ):
        self.ingestion_controller = kpiTrackerController(db)
        return await self.ingestion_controller.get_ingestion_logs(limit=limit, source_type=source_type)


# ─── Router instance ─────────────────────────────────────────────────────
router = IngestionRouter().router
