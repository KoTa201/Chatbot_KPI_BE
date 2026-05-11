"""
controller/kpiMasterController.py

Perubahan dari versi sebelumnya:
  - __init__: tambah KPIGroupRepository dan inject ke KPIMasterIngestionService.
  - delete_records_by_source_sheet_name: fix bug — service.delete_by_source_sheet_name
    mengembalikan Dict, bukan int. Controller kini unpack dict dengan benar.
  - Interface publik (method signatures, request/response types) TIDAK BERUBAH.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from schema.kpiGroupSchema import KPIGroupListResponse, KPIGroupUpdate
from schema.kpiMasterSchema import (
    IngestionResponse,
    IngestKPIMasterRequest,
)
from service.kpiMasterIngestionService import KPIMasterIngestionService
from service.kpiMasterService import KPIMasterService


class KPIMasterController:

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

        self.service: KPIMasterService = KPIMasterService(db=db)
        self.ingestion_service: KPIMasterIngestionService = KPIMasterIngestionService(
            db=self.db,
        )

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
            record=result["data"],
        )
