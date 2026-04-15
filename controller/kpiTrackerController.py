"""
controller/KPITrackerController.py

Perubahan dari versi sebelumnya:
  - __init__: tambah KPIGroupRepository dan IngestionLogRepository;
    IngestionService diganti TrackerIngestionService.
  - get_ingestion_logs: dihapus dari repo tracker (pindah ke IngestionLogRepository),
    controller kini langsung pakai log_repo.
  - Interface publik (semua method signatures dan response types) TIDAK BERUBAH.
"""

import re
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.IngestionLog import IngestionLogORM
from model.KPIGroup import KPIGroupORM
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
            tahun=request.tahun,
            nama_orang_override=request.nama_orang_override,
            skip_on_error=request.skip_on_error,
        )

    async def ingest_batch_from_google_sheets(
        self,
        request: BatchTrackerIngestionRequest,
    ) -> BatchTrackerIngestionResponse:
        """
        Ingest beberapa spreadsheet sekaligus.
        Setiap sumber membawa sheet_url + tahun masing-masing.
        """
        return await self.ingestion_service.ingest_batch(
            sources=request.sources,
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
        # source_type None = ambil semua jenis log (tracker + master)
        effective_source_type = source_type

        try:
            if effective_source_type in (None, "kpi_tracker", "kpi_master"):
                # Untuk tracker/master, tampilkan latest log per source_id (per KPI Group),
                # bukan per tab/bulan.
                latest_query = select(IngestionLogORM)
                if effective_source_type:
                    latest_query = latest_query.where(
                        IngestionLogORM.source_type == effective_source_type
                    )
                else:
                    latest_query = latest_query.where(
                        IngestionLogORM.source_type.in_(
                            ["kpi_tracker", "kpi_master"])
                    )

                latest_query = (
                    latest_query
                    .order_by(
                        IngestionLogORM.source_type,
                        IngestionLogORM.source_id,
                        IngestionLogORM.created_at.desc(),
                    )
                    .distinct(IngestionLogORM.source_type, IngestionLogORM.source_id)
                    .limit(limit)
                )
                latest_result = await self.db.execute(latest_query)
                latest_logs = latest_result.scalars().all()

                group_ids = [
                    log.source_id for log in latest_logs if log.source_id]
                groups_map = {}
                if group_ids:
                    group_result = await self.db.execute(
                        select(KPIGroupORM).where(
                            KPIGroupORM.id.in_(group_ids))
                    )
                    groups = group_result.scalars().all()
                    groups_map = {g.id: g for g in groups}

                logs_payload = []
                for log in latest_logs:
                    group = groups_map.get(log.source_id)
                    logs_payload.append(
                        {
                            "id":          log.id,
                            "sheet_name":  (group.nama_grup if group else log.sheet_name),
                            "nama_orang":  (
                                self._extract_nama_orang_from_group(
                                    group.nama_grup)
                                if group and log.source_type == "kpi_tracker"
                                else None
                            ),
                            "total_rows":  log.total_rows,
                            "ingested":    log.ingested_count,
                            "failed":      log.failed_count,
                            "status":      log.status,
                            "source_type": log.source_type,
                            "source_id":   log.source_id,
                            "created_at":  log.created_at,
                        }
                    )

                return {
                    "total": len(logs_payload),
                    "logs": logs_payload,
                }

            query = select(IngestionLogORM)
            if effective_source_type:
                query = query.where(
                    IngestionLogORM.source_type == effective_source_type)

            query = query.order_by(
                IngestionLogORM.created_at.desc()).limit(limit)
            result = await self.db.execute(query)
            logs = result.scalars().all()

            return {
                "total": len(logs),
                "logs": [
                    {
                        "id":          log.id,
                        "sheet_name":  log.sheet_name,
                        "nama_orang":  None,
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

    @staticmethod
    def _extract_nama_orang_from_group(nama_grup: Optional[str]) -> Optional[str]:
        if not nama_grup:
            return None

        # Pola umum: KPI_Tracker_<Nama Orang>_<Tahun>
        match = re.match(r"^KPI_Tracker_(.+?)_(20\d{2})$", nama_grup)
        if match:
            return match.group(1).replace("_", " ").strip()

        return None
