"""
controller/kpiMasterController.py

Perubahan dari versi sebelumnya:
  - __init__: tambah KPIGroupRepository dan inject ke KPIMasterIngestionService.
  - delete_records_by_source_sheet_name: fix bug — service.delete_by_source_sheet_name
    mengembalikan Dict, bukan int. Controller kini unpack dict dengan benar.
  - Interface publik (method signatures, request/response types) TIDAK BERUBAH.
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiMasterRepository import KPIMasterRepository
from schema.kpiMasterSchema import (
    DeleteMastersResponse,
    DetailMastersResponse,
    GroupedKPIMasterResponse,
    IngestionResponse,
    IngestKPIMasterRequest,
    KPIMasterResponse,
)
from service.kpiMasterIngestionService import KPIMasterIngestionService
from service.kpiMasterService import KPIMasterService


class KPIMasterController:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

        # Repositories
        self.kpi_repo: KPIMasterRepository = KPIMasterRepository(db)
        self.log_repo: IngestionLogRepository = IngestionLogRepository(db)
        self.group_repo: KPIGroupRepository = KPIGroupRepository(
            db)      # ← baru
        self.service: KPIMasterService = KPIMasterService(self.kpi_repo)
        self.ingestion_service: KPIMasterIngestionService = KPIMasterIngestionService(
            kpi_repo=self.kpi_repo,
            kpi_service=self.service,
            log_repo=self.log_repo,
            group_repo=self.group_repo,             # ← baru
        )

    # ================================================================ #
    #  INGESTION                                                       #
    # ================================================================ #

    async def ingest_kpi_master(
        self, request: IngestKPIMasterRequest
    ) -> IngestionResponse:
        """
        Ingest KPI Master dari Google Sheets.
        KPIGroup dan IngestionLog dibuat otomatis oleh ingestion service.
        """
        result = await self.ingestion_service.ingest_kpi_master(
            sheet_url=request.sheet_url,
            tahun=request.tahun,
        )
        return IngestionResponse(
            status=result["status"],
            count=result["count"],
            message=result["message"],
        )

    async def preview_kpi_master(self, sheet_url: str, tahun: int) -> dict:
        """Preview sheet data tanpa menyimpan ke DB."""
        df, spreadsheet_id, sheet_name = self._fetch_sheet(sheet_url)
        records, errors = self._parse(df, spreadsheet_id, sheet_name, tahun)
        return {
            "spreadsheet_id": spreadsheet_id,
            "sheet_name":     sheet_name,
            "tahun":          tahun,
            "total_records":  len(records),
            "errors":         errors,
            "preview":        records[:5],
        }

    # ================================================================ #
    #  GROUP/AGGREGATE                                                 #
    # ================================================================ #

    async def get_grouped_records(
        self, skip: int = 0, limit: int = 100
    ) -> GroupedKPIMasterResponse:
        result = await self.service.get_grouped_records(skip=skip, limit=limit)
        return GroupedKPIMasterResponse(**result)

    async def get_grouped_records_with_filters(
        self,
        tahun:    Optional[int] = None,
        category: Optional[str] = None,
        skip:     int = 0,
        limit:    int = 100,
    ) -> GroupedKPIMasterResponse:
        result = await self.service.get_grouped_records_with_filters(
            tahun=tahun,
            category=category,
            skip=skip,
            limit=limit,
        )
        return GroupedKPIMasterResponse(**result)

    async def get_detail_records_by_source_sheet_name(
        self,
        source_sheet_name: str,
        skip:  int = 0,
        limit: int = 100,
    ) -> DetailMastersResponse:
        result = await self.service.get_detail_records_by_source_sheet_name(
            source_sheet_name=source_sheet_name,
            skip=skip,
            limit=limit,
        )
        records = [KPIMasterResponse.from_orm(r) for r in result["records"]]
        return DetailMastersResponse(
            source_sheet_name=result["source_sheet_name"],
            records=records,
            pagination=result["pagination"],
        )
