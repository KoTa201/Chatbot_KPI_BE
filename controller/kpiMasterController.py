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

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiMasterRepository import KPIMasterRepository
from schema.kpiGroupSchema import KPIGroupListResponse, KPIGroupUpdate
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

    async def list_master_groups(
        self,
        page: int = 1,
        limit: int = 10,
    ) -> KPIGroupListResponse:
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'limit' harus antara 1 dan 100.",
            )
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page' tidak boleh negatif dan minimal 1.",
            )
        from service.kpiGroupService import KPIGroupService

        return await KPIGroupService(self.db).list_groups(
            page=page,
            limit=limit,
            group_type="master",
            search=None,
        )

    async def update_and_reingest(
        self,
        group_id: UUID,
        payload: KPIGroupUpdate,
    ) -> IngestionResponse:
        result = await self.ingestion_service.update_and_reingest(
            group_id=group_id,
            sheet_url=str(payload.sheet_url) if payload.sheet_url else None,
            tahun=payload.tahun,
        )
        return IngestionResponse(
            status=result["status"],
            count=result["count"],
            message=result["message"],
        )

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
