"""
router/ingestionRouter.py
Class-based router untuk ingestion endpoints.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiTrackerController import KPITrackerController
from databaseConfig import get_db
from schema.kpiTrackerSchema import (
    BatchTrackerIngestionRequest,
    BatchTrackerIngestionResponse,
    BulkIngestionResponse,
    IngestAllSheetsRequest,
)


class IngestionRouter:
    """Router untuk endpoints ingestion data KPI."""

    def __init__(self):
        self.router = APIRouter()
        self.setup_routes()

    def _get_controller(self, db: AsyncSession) -> KPITrackerController:
        return KPITrackerController(db)

    def setup_routes(self):
        """Register all routes."""

        # ── Ingestion ──────────────────────────────────────────────── #
        self.router.add_api_route(
            "/google-sheets/batch",
            self.ingest_batch_from_google_sheets,
            methods=["POST"],
            response_model=BatchTrackerIngestionResponse,
            summary="Batch ingest KPI dari beberapa Google Sheets",
        )
        self.router.add_api_route(
            "/google-sheets",
            self.ingest_from_google_sheets,
            methods=["POST"],
            response_model=BulkIngestionResponse,
            summary="Ingest KPI dari Google Sheets",
        )
        self.router.add_api_route(
            "/logs",
            self.get_ingestion_logs,
            methods=["GET"],
            summary="Riwayat ingestion",
        )

    # ── Ingestion handlers ─────────────────────────────────────────── #

    async def ingest_from_google_sheets(
        self,
        sheet_url: str = Query(..., description="URL Google Sheets"),
        nama_orang_override: Optional[str] = Query(
            default=None, description="Override nama orang jika tidak bisa diekstrak"
        ),
        skip_on_error: bool = Query(
            default=True, description="Lewati sheet yang gagal atau batalkan seluruh proses"
        ),
        db: AsyncSession = Depends(get_db),
    ):
        request = IngestAllSheetsRequest(
            sheet_url=sheet_url,
            nama_orang_override=nama_orang_override,
            skip_on_error=skip_on_error,
        )
        return await self._get_controller(db).ingest_all_sheets_from_google_sheets(request)

    async def ingest_batch_from_google_sheets(
        self,
        request: BatchTrackerIngestionRequest,
        db: AsyncSession = Depends(get_db),
    ) -> BatchTrackerIngestionResponse:
        return await self._get_controller(db).ingest_batch_from_google_sheets(request)

    async def get_ingestion_logs(
        self,
        limit: int = Query(default=20, le=100),
        source_type: Optional[Literal["kpi_tracker",
                                      "kpi_master"]] = Query(default=None),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_ingestion_logs(
            limit=limit, source_type=source_type
        )


# ─── Router instance ──────────────────────────────────────────────────────
router = IngestionRouter().router
