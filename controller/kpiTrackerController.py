"""
controllers/kpiTrackerController.py
Controller untuk KPI Tracker management.
"""

from typing import Optional, Dict, Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.kpiTrackerRepository import kpiTrackerRepository
from service.kpiTrackerService import KPITrackerService
from service.ingestionService import IngestionService
from schema.kpiTrackerSchema import (
    # Request schemas
    CreateKPIRecordRequest,
    UpdateKPIRecordRequest,
    BulkCreateKPIRecordsRequest,
    BulkDeleteKPIRecordsRequest,
    IngestAllSheetsRequest,
    # Response schemas
    KPIRecordResponse,
    ListResponse,
    GroupedKPIResponse,
    DetailRecordsResponse,
    BulkCreateResponse,
    BulkDeleteResponse,
    DeleteResponse,
    CountResponse,
    BulkIngestionResponse,
    # Legacy schemas
    IngestionResponse,
    SheetMeta,
)
from service.googleSheetService import GoogleSheetService
from utils.parser import parse_dataframe


class kpiTrackerController:

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.repo = kpiTrackerRepository(db) if db else None
        self.service = KPITrackerService(self.repo) if self.repo else None
        self.ingestion_service = IngestionService(
            self.repo, self.service) if (self.repo and self.service) else None

    # ------------------------------------------------------------------ #
    #  POST /ingest/google-sheets  (semua sheet)                           #
    # ------------------------------------------------------------------ #

    async def ingest_all_sheets_from_google_sheets(
        self,
        request: IngestAllSheetsRequest,
    ) -> BulkIngestionResponse:
        """
        Ingest semua sheet dalam satu spreadsheet via service.

        Args:
            request: IngestAllSheetsRequest dengan sheet_url dan options

        Returns:
            BulkIngestionResponse: Agregasi result per-sheet + grand total
        """
        return await self.ingestion_service.ingest_all_sheets(
            sheet_url=request.sheet_url,
            nama_orang_override=request.nama_orang_override,
            skip_on_error=request.skip_on_error,
        )

    # ------------------------------------------------------------------ #
    #  GET /ingest/logs                                                    #
    # ------------------------------------------------------------------ #

    async def get_ingestion_logs(self, limit: int, source_type: Optional[str] = None) -> dict:
        logs = await self.repo.get_ingestion_logs(limit, source_type=source_type)
        return {
            "total": len(logs),
            "logs": [
                {
                    "id":          log.id,
                    "sheet_name":  log.sheet_name,
                    "nama_orang":  log.nama_orang,
                    "total_rows":  log.total_rows,
                    "ingested":    log.ingested_count,
                    "failed":      log.failed_count,
                    "status":      log.status,
                    "source_type": log.source_type,
                    "created_at":  log.created_at,
                }
                for log in logs
            ],
        }

    # ================================================================ #
    #  CREATE Operations                                               #
    # ================================================================ #

    async def bulk_create_records(self, request: BulkCreateKPIRecordsRequest) -> BulkCreateResponse:
        """
        Buat multiple KPI records sekaligus (bulk insert).

        Args:
            request: BulkCreateKPIRecordsRequest dengan list record data

        Returns:
            BulkCreateResponse: Hasil bulk create dengan count dan status
        """
        records_dict = [r.dict() for r in request.records]
        result = await self.service.bulk_create_records(records_dict)
        return BulkCreateResponse(**result)

    # ================================================================ #
    #  READ Operations                                                 #
    # ================================================================ #

    async def get_record_by_id(self, record_id: UUID) -> KPIRecordResponse:
        """
        Ambil satu KPI record by ID.

        Args:
            record_id: UUID dari record

        Returns:
            KPIRecordResponse: KPI record detail
        """
        result = await self.service.get_record_by_id(record_id)
        return KPIRecordResponse.from_orm(result)

    async def get_all_records(self,
                              nama_kpi: Optional[str] = None,
                              tahun: Optional[int] = None,
                              nama_orang: Optional[str] = None,
                              skip: int = 0,
                              limit: int = 100) -> ListResponse:
        """
        Ambil semua KPI records dengan optional filters dan pagination.

        Args:
            nama_kpi: Filter by nama KPI
            tahun: Filter by tahun
            nama_orang: Filter by nama orang
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            ListResponse dengan records dan pagination info
        """
        result = await self.service.get_all_records(
            nama_kpi=nama_kpi,
            tahun=tahun,
            nama_orang=nama_orang,
            skip=skip,
            limit=limit
        )
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return ListResponse(
            records=records,
            pagination=result["pagination"]
        )

    async def get_records_by_tahun(self, tahun: int, skip: int = 0, limit: int = 100) -> ListResponse:
        """
        Ambil KPI records untuk tahun tertentu.

        Args:
            tahun: Tahun yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            ListResponse dengan records dan pagination info
        """
        result = await self.service.get_records_by_tahun(tahun, skip, limit)
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return ListResponse(
            records=records,
            pagination=result["pagination"]
        )

    async def get_records_count(self) -> CountResponse:
        """
        Ambil total count KPI records.

        Returns:
            CountResponse dengan total count
        """
        result = await self.service.get_records_count()
        return CountResponse(**result)

    # ================================================================ #
    #  GROUP/AGGREGATE Operations (Grouped by Nama KPI)                #
    # ================================================================ #

    async def get_grouped_records(self, skip: int = 0, limit: int = 100) -> GroupedKPIResponse:
        """
        Ambil KPI records yang dikelompokkan berdasarkan nama_kpi.
        Setiap group menampilkan: nama_kpi, total_count, tahun_list, sheet_names, sheet_count, last_updated.

        Args:
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            GroupedKPIResponse dengan groups dan pagination info
        """
        result = await self.service.get_grouped_records(skip=skip, limit=limit)
        return GroupedKPIResponse(**result)

    async def get_grouped_records_with_filters(self,
                                               tahun: Optional[int] = None,
                                               nama_orang: Optional[str] = None,
                                               skip: int = 0,
                                               limit: int = 100) -> GroupedKPIResponse:
        """
        Ambil KPI records grouped by nama_kpi dengan optional filters.

        Args:
            tahun: Filter by tahun
            nama_orang: Filter by nama orang
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            GroupedKPIResponse dengan filtered groups dan pagination info
        """
        result = await self.service.get_grouped_records_with_filters(
            tahun=tahun,
            nama_orang=nama_orang,
            skip=skip,
            limit=limit
        )
        return GroupedKPIResponse(**result)

    async def get_detail_records_by_nama_kpi(self, nama_kpi: str, skip: int = 0, limit: int = 100) -> DetailRecordsResponse:
        """
        Ambil detail records untuk satu nama_kpi tertentu (expand group).
        Menampilkan semua individual records dalam satu group KPI.

        Args:
            nama_kpi: Nama KPI yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            DetailRecordsResponse dengan detail records dan pagination info
        """
        result = await self.service.get_detail_records_by_nama_kpi(nama_kpi, skip, limit)
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return DetailRecordsResponse(
            nama_kpi=result["nama_kpi"],
            records=records,
            pagination=result["pagination"]
        )

    # ================================================================ #
    #  UPDATE Operations                                               #
    # ================================================================ #

    async def update_record(self, record_id: UUID, request: UpdateKPIRecordRequest) -> KPIRecordResponse:
        """
        Update KPI record.

        Args:
            record_id: UUID dari record yang diupdate
            request: UpdateKPIRecordRequest dengan field yang diupdate

        Returns:
            KPIRecordResponse: KPI record yang sudah diupdate
        """
        result = await self.service.update_record(record_id, request.dict(exclude_unset=True))
        return KPIRecordResponse.from_orm(result)

    # ================================================================ #
    #  DELETE Operations                                               #
    # ================================================================ #

    async def delete_record(self, record_id: UUID) -> DeleteResponse:
        """
        Hapus satu KPI record.

        Args:
            record_id: UUID dari record yang dihapus

        Returns:
            DeleteResponse dengan message
        """
        result = await self.service.delete_record(record_id)
        return DeleteResponse(**result)

    async def delete_records_by_ids(self, request: BulkDeleteKPIRecordsRequest) -> BulkDeleteResponse:
        """
        Hapus multiple KPI records.

        Args:
            request: BulkDeleteKPIRecordsRequest dengan list record IDs

        Returns:
            BulkDeleteResponse dengan count dan status
        """
        result = await self.service.delete_records_by_ids(request.record_ids)
        return BulkDeleteResponse(**result)
