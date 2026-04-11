"""
controller/kpiMasterController.py
"""

from typing import Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.kpiMasterRepository import KPIMasterRepository
from repository.ingestionLogRepository import IngestionLogRepository
from service.kpiMasterService import KPIMasterService
from service.kpiMasterIngestionService import KPIMasterIngestionService
from schema.kpiMasterSchema import (
    # Request schemas
    IngestKPIMasterRequest,
    # Response schemas
    KPIMasterResponse,
    GroupedKPIMasterResponse,
    DetailMastersResponse,
    IngestionResponse,
)


class KPIMasterController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kpi_repo = KPIMasterRepository(db)
        self.log_repo = IngestionLogRepository(db)
        self.service = KPIMasterService(self.kpi_repo)
        self.ingestion_service = KPIMasterIngestionService(
            self.kpi_repo, self.service, self.log_repo)

    async def ingest_kpi_master(self, request: IngestKPIMasterRequest) -> IngestionResponse:
        """
        Ingest KPI Master dari Google Sheets untuk tahun tertentu via service.

        Args:
            request: IngestKPIMasterRequest dengan sheet_url dan tahun

        Returns:
            IngestionResponse dengan status, count, dan message
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
        """Preview sheet data without saving."""
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
    #  GROUP/AGGREGATE Operations (Grouped by Source Sheet Name)        #
    # ================================================================ #

    async def get_grouped_records(self, skip: int = 0, limit: int = 100) -> GroupedKPIMasterResponse:
        """
        Ambil KPI Masters yang dikelompokkan berdasarkan source_sheet_name (nama file).
        Setiap group menampilkan: source_sheet_name, total_count, tahun_list, categories, kpi_count, last_updated.

        Args:
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            GroupedKPIMasterResponse dengan groups dan pagination info
        """
        result = await self.service.get_grouped_records(skip=skip, limit=limit)
        return GroupedKPIMasterResponse(**result)

    async def get_grouped_records_with_filters(self,
                                               tahun: Optional[int] = None,
                                               category: Optional[str] = None,
                                               skip: int = 0,
                                               limit: int = 100) -> GroupedKPIMasterResponse:
        """
        Ambil KPI Masters grouped by source_sheet_name dengan optional filters.

        Args:
            tahun: Filter by tahun
            category: Filter by category
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            GroupedKPIMasterResponse dengan filtered groups dan pagination info
        """
        result = await self.service.get_grouped_records_with_filters(
            tahun=tahun,
            category=category,
            skip=skip,
            limit=limit
        )
        return GroupedKPIMasterResponse(**result)

    async def get_detail_records_by_source_sheet_name(self,
                                                      source_sheet_name: str,
                                                      skip: int = 0,
                                                      limit: int = 100) -> DetailMastersResponse:
        """
        Ambil detail masters untuk satu source_sheet_name tertentu (expand group).
        Menampilkan semua individual masters dalam satu file group.

        Args:
            source_sheet_name: Nama file yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            DetailMastersResponse dengan detail records dan pagination info
        """
        result = await self.service.get_detail_records_by_source_sheet_name(
            source_sheet_name=source_sheet_name,
            skip=skip,
            limit=limit
        )
        records = [KPIMasterResponse.from_orm(r) for r in result["records"]]
        return DetailMastersResponse(
            source_sheet_name=result["source_sheet_name"],
            records=records,
            pagination=result["pagination"]
        )

    # ================================================================ #
    #  Private Helpers                                                 #
    # ================================================================ #

    def _fetch_sheet(self, sheet_url: str):
        """Fetch first sheet as raw DataFrame (no header)."""
        try:
            from service.googleSheetService import GoogleSheetService
            svc = GoogleSheetService()
            df, spreadsheet_id, sheet_name, _ = svc.fetch_sheet_as_dataframe(
                sheet_url=sheet_url,
                sheet_name=None,
                sheet_index=0,
                header=None,
            )
            return df, spreadsheet_id, sheet_name
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error fetching sheet: {str(e)}")

    def _parse(self, df, spreadsheet_id: str, sheet_name: str, tahun: int):
        """Parse dataframe to KPI Master records."""
        try:
            from utils.kpiMasterParser import parse_kpi_master_dataframe
            return parse_kpi_master_dataframe(df, spreadsheet_id, sheet_name, tahun=tahun)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
