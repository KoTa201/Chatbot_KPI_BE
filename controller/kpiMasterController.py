"""
controller/kpiMasterController.py
"""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiMasterRepository import KPIMasterRepository
from service.googleSheetService import GoogleSheetService
from utils.kpiMasterParser import parse_kpi_master_dataframe


class KPIMasterController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kpi_repo = KPIMasterRepository(db)
        self.log_repo = IngestionLogRepository(db)

    async def ingest_kpi_master(self, sheet_url: str, tahun: int) -> dict:
        """Upsert KPI Master records from Google Sheets for the given year."""
        df, spreadsheet_id, sheet_name = self._fetch_sheet(sheet_url)

        records, errors = self._parse(df, spreadsheet_id, sheet_name, tahun)
        ingested = await self.kpi_repo.upsert_by_tahun(records)

        status = "success" if not errors else (
            "partial" if ingested > 0 else "failed")
        await self.log_repo.create_ingestion_log(
            sheet_url=sheet_url,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
            nama_orang=None,
            total_rows=len(records) + len(errors),
            ingested_count=ingested,
            errors=errors,
            status=status,
            source_type="kpi_master",
        )

        return {
            "sheet_id":   spreadsheet_id,
            "sheet_name": sheet_name,
            "tahun":      tahun,
            "total_rows": len(records) + len(errors),
            "ingested":   ingested,
            "failed":     len(errors),
            "errors":     errors,
            "status":     status,
        }

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

    def _fetch_sheet(self, sheet_url: str):
        """Fetch first sheet as raw DataFrame (no header)."""
        try:
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
        try:
            return parse_kpi_master_dataframe(df, spreadsheet_id, sheet_name, tahun=tahun)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
