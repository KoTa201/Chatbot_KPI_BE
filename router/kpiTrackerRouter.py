"""
router/ingestionRouter.py
Class-based router untuk ingestion endpoints.
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from controller.kpiTrackerController import KPITrackerController
from databaseConfig import get_db
from schema.kpiTrackerSchema import (
    BulkIngestionResponse,
    BulkCreateKPIRecordsRequest,
    BulkDeleteKPIRecordsRequest,
    BulkCreateResponse,
    BulkDeleteResponse,
    CountResponse,
    DeleteResponse,
    DetailRecordsResponse,
    GroupedKPIResponse,
    IngestAllSheetsRequest,
    KPIRecordResponse,
    ListResponse,
    UpdateKPIRecordRequest,
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

        # ── CREATE ─────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/records/bulk",
            self.bulk_create_records,
            methods=["POST"],
            response_model=BulkCreateResponse,
            summary="Bulk create KPI records",
        )

        # ── READ ───────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/records/count",
            self.get_records_count,
            methods=["GET"],
            response_model=CountResponse,
            summary="Total count KPI records",
        )
        self.router.add_api_route(
            "/records/grouped",
            self.get_grouped_records,
            methods=["GET"],
            response_model=GroupedKPIResponse,
            summary="KPI records dikelompokkan berdasarkan nama_kpi",
        )
        self.router.add_api_route(
            "/records/grouped/filter",
            self.get_grouped_records_with_filters,
            methods=["GET"],
            response_model=GroupedKPIResponse,
            summary="KPI records grouped dengan filter tahun/nama_orang",
        )
        self.router.add_api_route(
            "/records/grouped/{nama_kpi}",
            self.get_detail_records_by_nama_kpi,
            methods=["GET"],
            response_model=DetailRecordsResponse,
            summary="Detail records untuk satu nama_kpi (expand group)",
        )
        self.router.add_api_route(
            "/records/tahun/{tahun}",
            self.get_records_by_tahun,
            methods=["GET"],
            response_model=ListResponse,
            summary="KPI records berdasarkan tahun",
        )
        self.router.add_api_route(
            "/records/{record_id}",
            self.get_record_by_id,
            methods=["GET"],
            response_model=KPIRecordResponse,
            summary="Ambil satu KPI record by ID",
        )
        self.router.add_api_route(
            "/records",
            self.get_all_records,
            methods=["GET"],
            response_model=ListResponse,
            summary="Ambil semua KPI records dengan filter dan pagination",
        )

        # ── UPDATE ─────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/records/{record_id}",
            self.update_record,
            methods=["PATCH"],
            response_model=KPIRecordResponse,
            summary="Update KPI record",
        )

        # ── DELETE ─────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/records/bulk",
            self.delete_records_by_ids,
            methods=["DELETE"],
            response_model=BulkDeleteResponse,
            summary="Bulk delete KPI records",
        )
        self.router.add_api_route(
            "/records/{record_id}",
            self.delete_record,
            methods=["DELETE"],
            response_model=DeleteResponse,
            summary="Hapus satu KPI record",
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

    # ── CREATE handlers ────────────────────────────────────────────── #

    async def bulk_create_records(
        self,
        request: BulkCreateKPIRecordsRequest,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).bulk_create_records(request)

    # ── READ handlers ──────────────────────────────────────────────── #

    async def get_all_records(
        self,
        nama_kpi: Optional[str] = Query(default=None),
        tahun: Optional[int] = Query(default=None),
        nama_orang: Optional[str] = Query(default=None),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_all_records(
            nama_kpi=nama_kpi,
            tahun=tahun,
            nama_orang=nama_orang,
            skip=skip,
            limit=limit,
        )

    async def get_record_by_id(
        self,
        record_id: UUID,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_record_by_id(record_id)

    async def get_records_by_tahun(
        self,
        tahun: int,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_records_by_tahun(tahun, skip, limit)

    async def get_records_count(self, db: AsyncSession = Depends(get_db)):
        return await self._get_controller(db).get_records_count()

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
        nama_orang: Optional[str] = Query(default=None),
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_grouped_records_with_filters(
            tahun=tahun, nama_orang=nama_orang, skip=skip, limit=limit
        )

    async def get_detail_records_by_nama_kpi(
        self,
        nama_kpi: str,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).get_detail_records_by_nama_kpi(
            nama_kpi, skip, limit
        )

    # ── UPDATE handlers ────────────────────────────────────────────── #

    async def update_record(
        self,
        record_id: UUID,
        request: UpdateKPIRecordRequest,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).update_record(record_id, request)

    # ── DELETE handlers ────────────────────────────────────────────── #

    async def delete_record(
        self,
        record_id: UUID,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).delete_record(record_id)

    async def delete_records_by_ids(
        self,
        request: BulkDeleteKPIRecordsRequest,
        db: AsyncSession = Depends(get_db),
    ):
        return await self._get_controller(db).delete_records_by_ids(request)


# ─── Router instance ──────────────────────────────────────────────────────
router = IngestionRouter().router
