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
            tahun=request.tahun,
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

    # ================================================================ #
    #  CREATE                                                          #
    # ================================================================ #

    async def bulk_create_records(
        self, request: BulkCreateKPIRecordsRequest
    ) -> BulkCreateResponse:
        records_dict = [r.dict() for r in request.records]
        result = await self.service.bulk_create_records(records_dict)
        return BulkCreateResponse(**result)

    # ================================================================ #
    #  READ                                                            #
    # ================================================================ #

    async def get_record_by_id(self, record_id: UUID) -> KPIRecordResponse:
        result = await self.service.get_record_by_id(record_id)
        return KPIRecordResponse.from_orm(result)

    async def get_all_records(
        self,
        nama_kpi:   Optional[str] = None,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> ListResponse:
        result = await self.service.get_all_records(
            nama_kpi=nama_kpi,
            tahun=tahun,
            nama_orang=nama_orang,
            skip=skip,
            limit=limit,
        )
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return ListResponse(records=records, pagination=result["pagination"])

    async def get_records_by_tahun(
        self, tahun: int, skip: int = 0, limit: int = 100
    ) -> ListResponse:
        result = await self.service.get_records_by_tahun(tahun, skip, limit)
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return ListResponse(records=records, pagination=result["pagination"])

    async def get_records_count(self) -> CountResponse:
        result = await self.service.get_records_count()
        return CountResponse(**result)

    # ================================================================ #
    #  GROUP / AGGREGATE                                               #
    # ================================================================ #

    async def get_grouped_records(
        self, skip: int = 0, limit: int = 100
    ) -> GroupedKPIResponse:
        result = await self.service.get_grouped_records(skip=skip, limit=limit)
        return GroupedKPIResponse(**result)

    async def get_grouped_records_with_filters(
        self,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> GroupedKPIResponse:
        result = await self.service.get_grouped_records_with_filters(
            tahun=tahun,
            nama_orang=nama_orang,
            skip=skip,
            limit=limit,
        )
        return GroupedKPIResponse(**result)

    async def get_detail_records_by_nama_kpi(
        self, nama_kpi: str, skip: int = 0, limit: int = 100
    ) -> DetailRecordsResponse:
        result = await self.service.get_detail_records_by_nama_kpi(
            nama_kpi, skip, limit
        )
        records = [KPIRecordResponse.from_orm(r) for r in result["records"]]
        return DetailRecordsResponse(
            nama_kpi=result["nama_kpi"],
            records=records,
            pagination=result["pagination"],
        )

    # ================================================================ #
    #  UPDATE                                                          #
    # ================================================================ #

    async def update_record(
        self, record_id: UUID, request: UpdateKPIRecordRequest
    ) -> KPIRecordResponse:
        result = await self.service.update_record(
            record_id, request.dict(exclude_unset=True)
        )
        return KPIRecordResponse.from_orm(result)

    # ================================================================ #
    #  DELETE                                                          #
    # ================================================================ #

    async def delete_record(self, record_id: UUID) -> DeleteResponse:
        result = await self.service.delete_record(record_id)
        return DeleteResponse(**result)

    async def delete_records_by_ids(
        self, request: BulkDeleteKPIRecordsRequest
    ) -> BulkDeleteResponse:
        result = await self.service.delete_records_by_ids(request.record_ids)
        return BulkDeleteResponse(**result)
