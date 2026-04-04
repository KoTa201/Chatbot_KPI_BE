"""
controllers/ingestion_controller.py
"""

from typing import Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionRepository import IngestionRepository
from schema.ingestionSchema import IngestionResponse, SheetMeta
from service.googleSheetService import GoogleSheetService
from utils.parser import parse_dataframe


class IngestionController:

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.repo = IngestionRepository(db) if db else None

    # ------------------------------------------------------------------ #
    #  POST /ingest/google-sheets  (semua sheet)                           #
    # ------------------------------------------------------------------ #

    async def ingest_all_sheets_from_google_sheets(
        self,
        sheet_url: str,
        nama_orang_override: Optional[str],
        skip_on_error: bool = True,
    ) -> dict:
        """
        Ingest semua sheet dalam satu spreadsheet.
        Return agregasi result per-sheet + grand total.
        """
        all_sheets = self._fetch_all_sheets(sheet_url, skip_on_error)

        sheets_result = []
        grand_total_rows = 0
        grand_ingested = 0
        grand_failed = 0

        for sheet in all_sheets:
            # Sheet gagal di-parse (kosong / format tidak sesuai)
            if sheet["error"]:
                sheets_result.append({
                    "sheet_name": sheet["sheet_name"],
                    "status":     "skipped",
                    "reason":     sheet["error"],
                })
                continue

            df = sheet["df"]
            meta = sheet["meta"]
            spreadsheet_id = sheet["spreadsheet_id"]
            active_sheet_name = sheet["sheet_name"]

            nama_orang = nama_orang_override or meta.get(
                "nama_orang") or "UNKNOWN"
            tahun = meta.get("tahun")

            # Parse DataFrame → records + errors
            records, errors = self._parse_records(
                df=df,
                nama_orang=nama_orang,
                tahun=tahun,
                spreadsheet_id=spreadsheet_id,
                active_sheet_name=active_sheet_name,
            )

            # Simpan ke DB
            ingested_count = await self.repo.bulk_insert_kpi_records(records)

            # Log per-sheet
            status = self._resolve_status(ingested_count, errors)
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

            grand_total_rows += len(df)
            grand_ingested += ingested_count
            grand_failed += len(errors)

            sheets_result.append({
                "log_id":     log.id,
                "sheet_name": active_sheet_name,
                "meta": SheetMeta(
                    nama_orang=nama_orang,
                    bulan=meta.get("bulan"),
                    bulan_num=meta.get("bulan_num"),
                    tahun=tahun,
                ),
                "total_rows": len(df),
                "ingested":   ingested_count,
                "failed":     len(errors),
                "errors":     errors,
                "status":     status,
            })

        return {
            "spreadsheet_url": sheet_url,
            "total_sheets_processed": len(sheets_result),
            "grand_total_rows": grand_total_rows,
            "grand_ingested":   grand_ingested,
            "grand_failed":     grand_failed,
            "overall_status":   self._resolve_status(grand_ingested, [] if grand_failed == 0 else ["x"]),
            "sheets":           sheets_result,
        }

    # ------------------------------------------------------------------ #
    #  POST /ingest/google-sheets  (single sheet — tetap dipertahankan)   #
    # ------------------------------------------------------------------ #

    async def ingest_from_google_sheets(
        self,
        sheet_url: str,
        sheet_name: Optional[str],
        sheet_index: int,
        nama_orang_override: Optional[str],
    ) -> IngestionResponse:
        df, spreadsheet_id, active_sheet_name, meta = self._fetch_sheet(
            sheet_url=sheet_url,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
        )

        nama_orang = nama_orang_override or meta.get("nama_orang") or "UNKNOWN"
        tahun = meta.get("tahun")

        records, errors = self._parse_records(
            df=df,
            nama_orang=nama_orang,
            tahun=tahun,
            spreadsheet_id=spreadsheet_id,
            active_sheet_name=active_sheet_name,
        )

        ingested_count = await self.repo.bulk_insert_kpi_records(records)

        status = self._resolve_status(ingested_count, errors)
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

        return IngestionResponse(
            log_id=log.id,
            sheet_id=spreadsheet_id,
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
        )

    # ------------------------------------------------------------------ #
    #  GET /ingest/sheets/tabs                                             #
    # ------------------------------------------------------------------ #

    async def list_sheet_tabs(self, sheet_url: str) -> dict:
        return {"tabs": GoogleSheetService().list_sheets(sheet_url)}

    # ------------------------------------------------------------------ #
    #  GET /ingest/sheets/preview                                          #
    # ------------------------------------------------------------------ #

    async def preview_sheet(
        self,
        sheet_url: str,
        sheet_name: Optional[str],
        sheet_index: int,
    ) -> dict:
        df, spreadsheet_id, active_sheet_name, meta = self._fetch_sheet(
            sheet_url=sheet_url,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
        )
        return {
            "spreadsheet_id":  spreadsheet_id,
            "sheet_name":      active_sheet_name,
            "extracted_meta":  meta,
            "columns":         df.columns.tolist(),
            "total_data_rows": len(df),
            "preview":         df.head(5).fillna("").to_dict(orient="records"),
        }

    # ------------------------------------------------------------------ #
    #  GET /ingest/logs                                                    #
    # ------------------------------------------------------------------ #

    async def get_ingestion_logs(self, limit: int, source_type: Optional[str] = None) -> dict:
        logs = await self.repo.get_ingestion_logs(limit, source_type=source_type)
        return {
            "total": len(logs),
            "logs": [
                {
                    "id":          log.id,
                    "sheet_name":  log.sheet_name,
                    "nama_orang":  log.nama_orang,
                    "total_rows":  log.total_rows,
                    "ingested":    log.ingested_count,
                    "failed":      log.failed_count,
                    "status":      log.status,
                    "source_type": log.source_type,
                    "created_at":  log.created_at,
                }
                for log in logs
            ],
        }

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_all_sheets(self, sheet_url: str, skip_on_error: bool) -> list:
        """Fetch semua sheet, wrap exception jadi HTTP 500."""
        try:
            return GoogleSheetService().fetch_all_sheets_as_dataframes(
                sheet_url=sheet_url,
                skip_on_error=skip_on_error,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error saat fetch semua sheet: {str(e)}",
            )

    def _fetch_sheet(
        self,
        sheet_url: str,
        sheet_name: Optional[str],
        sheet_index: int,
    ):
        """Fetch satu sheet, wrap exception jadi HTTP 500."""
        try:
            return GoogleSheetService().fetch_sheet_as_dataframe(
                sheet_url=sheet_url,
                sheet_name=sheet_name,
                sheet_index=sheet_index,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error saat fetch Google Sheets: {str(e)}",
            )

    def _parse_records(
        self,
        df,
        nama_orang: str,
        tahun: Optional[int],
        spreadsheet_id: str,
        active_sheet_name: str,
    ):
        """Parse DataFrame → (records, errors). Raise HTTP 422 jika format tidak valid."""
        try:
            return parse_dataframe(
                df=df,
                nama_orang=nama_orang,
                tahun_override=tahun,
                spreadsheet_id=spreadsheet_id,
                sheet_name=active_sheet_name,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    @staticmethod
    def _resolve_status(ingested_count: int, errors: list) -> str:
        if not errors:
            return "success"
        if ingested_count > 0:
            return "partial"
        return "failed"
