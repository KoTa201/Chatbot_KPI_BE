"""
controller/KPITrackerController.py

Responsibilities:
  - Handle KPI Tracker ingestion requests
  - Validate input dan orchestrate ingestion process
  - Call TrackerIngestionService untuk business logic
  
Methods:
  - ingest_all_sheets_from_google_sheets: Ingest semua sheet dari satu spreadsheet
  - ingest_batch_from_google_sheets: Batch ingest dari multiple spreadsheets

Note: get_ingestion_logs dipindahkan ke IngestionLogController
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiTrackerRepository import KPITrackerRepository
from schema.kpiTrackerSchema import (
    BatchTrackerIngestionRequest,
    BatchTrackerIngestionResponse,
    BulkIngestionResponse,
    IngestAllSheetsRequest,
    UrlIngestionResult,
)
from service.TrackeringestionService import TrackerIngestionService


class KPITrackerController:

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

        # Repositories
        self.tracker_repo: KPITrackerRepository = KPITrackerRepository(
            db) if db else None
        self.log_repo: IngestionLogRepository = IngestionLogRepository(
            db) if db else None
        self.group_repo: KPIGroupRepository = KPIGroupRepository(
            db) if db else None
        self.ingestion_service: TrackerIngestionService = (
            TrackerIngestionService(
                db=db,
                tracker_repo=self.tracker_repo,
                log_repo=self.log_repo,
                group_repo=self.group_repo,
            )
            if db else None
        )

    # ================================================================ #
    #  INGESTION                                                       #
    # ================================================================ #

    async def ingest_all_sheets_from_google_sheets(
        self,
        request: IngestAllSheetsRequest,
    ) -> BulkIngestionResponse:
        """
        Ingest semua sheet dalam satu spreadsheet.
        KPIGroup dan IngestionLog dibuat otomatis per spreadsheet/tab.
        """
        raw = await self.ingestion_service.ingest_all_sheets(
            sheet_url=request.sheet_url,
            tahun=request.tahun,
            nama_orang_override=request.nama_orang_override,
            skip_on_error=request.skip_on_error,
        )
        return BulkIngestionResponse(
            spreadsheet_url=raw["spreadsheet_url"],
            total_sheets_processed=raw["total_sheets_processed"],
            grand_total_rows=raw["grand_total_rows"],
            grand_ingested=raw["grand_ingested"],
            grand_failed=raw["grand_failed"],
            overall_status=raw["overall_status"],
            sheets=raw["sheets"],
        )

    async def ingest_batch_from_google_sheets(
        self,
        request: BatchTrackerIngestionRequest,
    ) -> BatchTrackerIngestionResponse:
        """
        Ingest beberapa spreadsheet sekaligus.
        Setiap sumber membawa sheet_url + tahun masing-masing.
        """
        raw = await self.ingestion_service.ingest_batch(
            sources=request.sources,
            skip_on_error=request.skip_on_error,
            delay_between_sources=request.delay_between_sources,
        )
        return BatchTrackerIngestionResponse(
            total_urls=raw["total_urls"],
            succeeded=raw["succeeded"],
            failed=raw["failed"],
            grand_total_rows=raw["grand_total_rows"],
            grand_ingested=raw["grand_ingested"],
            grand_failed=raw["grand_failed"],
            results=[
                UrlIngestionResult(**r) for r in raw["results"]
            ],
        )
