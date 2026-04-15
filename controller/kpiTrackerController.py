"""
controller/KPITrackerController.py

Perubahan dari versi sebelumnya:
  - __init__: tambah KPIGroupRepository dan IngestionLogRepository;
    IngestionService diganti TrackerIngestionService.
  - get_ingestion_logs: dihapus dari repo tracker (pindah ke IngestionLogRepository),
    controller kini langsung pakai log_repo.
  - Interface publik (semua method signatures dan response types) TIDAK BERUBAH.
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
)
from service.TrackeringestionService import TrackerIngestionService


class KPITrackerController:

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db

        # Repositories
        self.tracker_repo = KPITrackerRepository(db) if db else None
        self.log_repo = IngestionLogRepository(db) if db else None
        self.group_repo = KPIGroupRepository(db) if db else None

        # Ingestion service — kini butuh db session (untuk master matching)
        self.ingestion_service = (
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
        return await self.ingestion_service.ingest_all_sheets(
            sheet_url=request.sheet_url,
            nama_orang_override=request.nama_orang_override,
            tahun=request.tahun,
            skip_on_error=request.skip_on_error,
        )

    async def ingest_batch_from_google_sheets(
        self,
        request: BatchTrackerIngestionRequest,
    ) -> BatchTrackerIngestionResponse:
        """
        Ingest beberapa spreadsheet Google Sheets sekaligus.
        """
        return await self.ingestion_service.ingest_batch(
            sheet_urls=request.sheet_urls,
            skip_on_error=request.skip_on_error,
        )

    # ================================================================ #
    #  INGESTION LOGS                                                  #
    # ================================================================ #

    async def get_ingestion_logs(
        self, limit: int, source_type: Optional[str] = None
    ) -> dict:
        """
        Ambil ingestion logs.
        Sebelumnya: repo.get_ingestion_logs (method yang tidak ada di repo baru).
        Sekarang: langsung dari IngestionLogRepository.
        """
        # source_type='kpi_tracker' untuk filter log tracker saja
        effective_source_type = source_type or "kpi_tracker"

        # Ambil semua group_id tracker dulu, lalu query log per source
        # Untuk simplisitas, query tanpa filter source_id (semua log kpi_tracker)
        try:
            from sqlalchemy import select
            from model.IngestionLog import IngestionLogORM

            query = (
                select(IngestionLogORM)
                .where(IngestionLogORM.source_type == effective_source_type)
                .order_by(IngestionLogORM.created_at.desc())
                .limit(limit)
            )
            result = await self.db.execute(query)
            logs = result.scalars().all()

            return {
                "total": len(logs),
                "logs": [
                    {
                        "id":          log.id,
                        "sheet_name":  log.sheet_name,
                        "total_rows":  log.total_rows,
                        "ingested":    log.ingested_count,
                        "failed":      log.failed_count,
                        "status":      log.status,
                        "source_type": log.source_type,
                        "source_id":   log.source_id,
                        "created_at":  log.created_at,
                    }
                    for log in logs
                ],
            }
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil ingestion logs: {str(e)}",
            )
