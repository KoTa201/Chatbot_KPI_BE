"""
services/kpiMasterIngestionService.py
Service untuk KPI Master ingestion dari Google Sheets.
"""

from typing import Optional, Dict, Any, List, Tuple
import logging

from fastapi import HTTPException

from repository.kpiMasterRepository import KPIMasterRepository
from repository.ingestionLogRepository import IngestionLogRepository
from service.kpiMasterService import KPIMasterService
from service.googleSheetService import GoogleSheetService
from utils.kpiMasterParser import parse_kpi_master_dataframe


logger = logging.getLogger(__name__)


class KPIMasterIngestionService:
    """Service untuk menangani ingestion KPI Master dari Google Sheets."""

    def __init__(self, repo: KPIMasterRepository, service: KPIMasterService, log_repo: IngestionLogRepository):
        self.repo = repo
        self.service = service
        self.log_repo = log_repo
        self.google_service = GoogleSheetService()

    async def ingest_kpi_master(
        self,
        sheet_url: str,
        tahun: int,
    ) -> Dict[str, Any]:
        """
        Ingest KPI Master dari Google Sheets untuk tahun tertentu.

        Args:
            sheet_url: URL Google Sheets
            tahun: Tahun untuk KPI Master

        Returns:
            Dict dengan hasil ingestion (count, status, message)
        """
        try:
            # Validasi tahun
            self.service._validate_tahun(tahun)

            # Fetch sheet
            df, spreadsheet_id, sheet_name = self._fetch_sheet(sheet_url)

            # Parse records
            records, errors = self._parse_records(
                df=df,
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                tahun=tahun,
            )

            # Upsert ke DB via service (bukan langsung repository)
            try:
                result = await self.service.upsert_records(records)
                ingested_count = result.get("count", len(records))
            except Exception as e:
                logger.error(f"Error upsert KPI Master records: {str(e)}")
                ingested_count = 0
                errors.append(f"Database error: {str(e)}")

            # Log ingestion
            status = self._resolve_status(ingested_count, errors)
            try:
                await self.log_repo.create_ingestion_log(
                    sheet_url=sheet_url,
                    spreadsheet_id=spreadsheet_id,
                    sheet_name=sheet_name,
                    nama_orang=None,
                    total_rows=len(records) + len(errors),
                    ingested_count=ingested_count,
                    errors=errors,
                    status=status,
                    source_type="kpi_master",
                )
            except Exception as e:
                logger.error(f"Error create ingestion log: {str(e)}")

            logger.info(
                f"Ingestion completed: {ingested_count} KPI Master records ingested")

            return {
                "status": status,
                "count": ingested_count,
                "message": f"Berhasil ingest {ingested_count} KPI Master records untuk tahun {tahun}",
                "sheet_id": spreadsheet_id,
                "sheet_name": sheet_name,
                "tahun": tahun,
                "total_rows": len(records) + len(errors),
                "failed": len(errors),
                "errors": errors,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error ingest KPI Master: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saat ingest KPI Master: {str(e)}",
            )

    # ================================================================ #
    #  Private Helpers                                                 #
    # ================================================================ #

    def _fetch_sheet(self, sheet_url: str) -> Tuple:
        """
        Fetch sheet dari Google Sheets.

        Args:
            sheet_url: URL Google Sheets

        Returns:
            Tuple (df, spreadsheet_id, sheet_name)

        Raises:
            HTTPException jika error
        """
        try:
            df, spreadsheet_id, sheet_name, _ = self.google_service.fetch_sheet_as_dataframe(
                sheet_url=sheet_url,
                sheet_name=None,
                sheet_index=0,
                header=None,
            )
            return df, spreadsheet_id, sheet_name
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetch sheet: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saat fetch Google Sheets: {str(e)}",
            )

    def _parse_records(
        self,
        df,
        spreadsheet_id: str,
        sheet_name: str,
        tahun: int,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Parse DataFrame → (records, errors).

        Args:
            df: DataFrame dari sheet
            spreadsheet_id: ID spreadsheet
            sheet_name: Nama sheet
            tahun: Tahun untuk record

        Returns:
            Tuple (records list, errors list)

        Raises:
            HTTPException jika format tidak valid
        """
        try:
            return parse_kpi_master_dataframe(
                df=df,
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
                tahun=tahun,
            )
        except ValueError as e:
            logger.error(f"Error parse records: {str(e)}")
            raise HTTPException(status_code=422, detail=str(e))

    @staticmethod
    def _resolve_status(ingested_count: int, errors: list) -> str:
        """
        Resolve status berdasarkan ingestion result.

        Args:
            ingested_count: Jumlah records yang berhasil
            errors: List errors

        Returns:
            Status: success / partial / failed
        """
        if not errors:
            return "success"
        if ingested_count > 0:
            return "partial"
        return "failed"
