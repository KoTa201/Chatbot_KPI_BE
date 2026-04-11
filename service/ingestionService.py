"""
services/ingestionService.py
Service untuk KPI Tracker ingestion dari Google Sheets.
"""

from typing import Optional, Dict, Any, List, Tuple
import logging
from datetime import datetime

from fastapi import HTTPException

from repository.kpiTrackerRepository import kpiTrackerRepository
from service.kpiTrackerService import KPITrackerService
from service.googleSheetService import GoogleSheetService
from schema.kpiTrackerSchema import (
    SheetMeta,
    SheetIngestionResult,
    BulkIngestionResponse,
)
from utils.parser import parse_dataframe


logger = logging.getLogger(__name__)


class IngestionService:
    """Service untuk menangani ingestion dari Google Sheets."""

    def __init__(self, repo: kpiTrackerRepository, service: KPITrackerService):
        self.repo = repo
        self.service = service
        self.google_service = GoogleSheetService()

    async def ingest_all_sheets(
        self,
        sheet_url: str,
        nama_orang_override: Optional[str] = None,
        skip_on_error: bool = True,
    ) -> BulkIngestionResponse:
        """
        Ingest semua sheet dalam satu spreadsheet.
        Aggregate result per-sheet + grand total.

        Args:
            sheet_url: URL Google Sheets
            nama_orang_override: Override nama_orang dari metadata
            skip_on_error: Skip sheet dengan error atau stop

        Returns:
            BulkIngestionResponse dengan detail per-sheet + grand total
        """
        try:
            # Fetch semua sheet
            all_sheets = self._fetch_all_sheets(sheet_url, skip_on_error)

            sheets_result: List[SheetIngestionResult] = []
            grand_total_rows = 0
            grand_ingested = 0
            grand_failed = 0

            for sheet in all_sheets:
                # Sheet gagal di-parse (kosong / format tidak sesuai)
                if sheet["error"]:
                    sheets_result.append(SheetIngestionResult(
                        log_id=None,
                        sheet_name=sheet["sheet_name"],
                        meta=None,
                        total_rows=None,
                        ingested=None,
                        failed=None,
                        errors=None,
                        status="skipped",
                        reason=sheet["error"],
                    ))
                    continue

                df = sheet["df"]
                meta = sheet["meta"]
                spreadsheet_id = sheet["spreadsheet_id"]
                active_sheet_name = sheet["sheet_name"]

                nama_orang = nama_orang_override or meta.get("nama_orang") or "UNKNOWN"
                tahun = meta.get("tahun")

                # Parse DataFrame → records + errors
                records, errors = self._parse_records(
                    df=df,
                    nama_orang=nama_orang,
                    tahun=tahun,
                    spreadsheet_id=spreadsheet_id,
                    active_sheet_name=active_sheet_name,
                )

                # Simpan ke DB via service (bukan langsung repository)
                try:
                    ingested_count = await self.service.bulk_create_records(records)
                    ingested_count = ingested_count.get("count", len(records))
                except Exception as e:
                    logger.error(f"Error bulk insert untuk sheet {active_sheet_name}: {str(e)}")
                    ingested_count = 0
                    errors.append(f"Database error: {str(e)}")

                # Log per-sheet via service
                status = self._resolve_status(ingested_count, errors)
                try:
                    log = await self.repo.create_ingestion_log(
                        sheet_url=sheet_url,
                        spreadsheet_id=spreadsheet_id,
                        sheet_name=active_sheet_name,
                        nama_orang=nama_orang,
                        total_rows=len(df),
                        ingested_count=ingested_count,
                        errors=errors,
                        status=status,
                        source_type="kpi_tracker",
                    )
                    log_id = log.id if log else None
                except Exception as e:
                    logger.error(f"Error create ingestion log: {str(e)}")
                    log_id = None

                grand_total_rows += len(df)
                grand_ingested += ingested_count
                grand_failed += len(errors)

                sheets_result.append(SheetIngestionResult(
                    log_id=log_id,
                    sheet_name=active_sheet_name,
                    meta=SheetMeta(
                        nama_orang=nama_orang,
                        bulan=meta.get("bulan"),
                        bulan_num=meta.get("bulan_num"),
                        tahun=tahun,
                    ),
                    total_rows=len(df),
                    ingested=ingested_count,
                    failed=len(errors),
                    errors=errors,
                    status=status,
                ))

            overall_status = self._resolve_status(grand_ingested, [] if grand_failed == 0 else ["error"])

            result = BulkIngestionResponse(
                spreadsheet_url=sheet_url,
                total_sheets_processed=len(sheets_result),
                grand_total_rows=grand_total_rows,
                grand_ingested=grand_ingested,
                grand_failed=grand_failed,
                overall_status=overall_status,
                sheets=sheets_result,
            )

            logger.info(f"Ingestion completed: {grand_ingested}/{grand_total_rows} records ingested")
            return result

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error ingest all sheets: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saat ingest sheets: {str(e)}",
            )

    # ================================================================ #
    #  Private Helpers                                                 #
    # ================================================================ #

    def _fetch_all_sheets(self, sheet_url: str, skip_on_error: bool) -> list:
        """
        Fetch semua sheet dari Google Sheets.

        Args:
            sheet_url: URL Google Sheets
            skip_on_error: Skip sheet dengan error

        Returns:
            List sheet dengan dataframe dan metadata

        Raises:
            HTTPException jika error
        """
        try:
            return self.google_service.fetch_all_sheets_as_dataframes(
                sheet_url=sheet_url,
                skip_on_error=skip_on_error,
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetch all sheets: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saat fetch semua sheet: {str(e)}",
            )

    def _parse_records(
        self,
        df,
        nama_orang: str,
        tahun: Optional[int],
        spreadsheet_id: str,
        active_sheet_name: str,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Parse DataFrame → (records, errors).

        Args:
            df: DataFrame dari sheet
            nama_orang: Nama orang untuk record
            tahun: Tahun untuk record
            spreadsheet_id: ID spreadsheet
            active_sheet_name: Nama sheet active

        Returns:
            Tuple (records list, errors list)

        Raises:
            HTTPException jika format tidak valid
        """
        try:
            return parse_dataframe(
                df=df,
                nama_orang=nama_orang,
                tahun_override=tahun,
                spreadsheet_id=spreadsheet_id,
                sheet_name=active_sheet_name,
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
            Status: success / partial / failed / skipped
        """
        if not errors:
            return "success"
        if ingested_count > 0:
            return "partial"
        return "failed"
