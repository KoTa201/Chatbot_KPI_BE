"""
controllers/ingestion_controller.py
Menangani logika bisnis, validasi input, dan pembentukan response
untuk semua endpoint ingestion KPI.
Operasi database didelegasikan ke IngestionRepository.
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
    #  POST /ingest/google-sheets                                          #
    # ------------------------------------------------------------------ #

    async def ingest_from_google_sheets(
        self,
        sheet_url: str,
        sheet_name: Optional[str],
        sheet_index: int,
        nama_orang_override: Optional[str],
    ) -> IngestionResponse:
        # 1. Fetch sheet + ekstrak meta otomatis dari judul
        df, spreadsheet_id, active_sheet_name, meta = self._fetch_sheet(
            sheet_url=sheet_url,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
        )

        # 2. Tentukan nama_orang: override > dari judul > fallback
        nama_orang = nama_orang_override or meta.get("nama_orang") or "UNKNOWN"
        tahun = meta.get("tahun")

        # 3. Parse DataFrame → records + errors
        records, errors = self._parse_records(
            df=df,
            nama_orang=nama_orang,
            tahun=tahun,
            spreadsheet_id=spreadsheet_id,
            active_sheet_name=active_sheet_name,
        )

        # 4. Simpan KPI records ke DB (via repository)
        ingested_count = await self.repo.bulk_insert_kpi_records(records)

        # 5. Tentukan status & simpan log ingestion (via repository)
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

    async def get_ingestion_logs(self, limit: int) -> dict:
        logs = await self.repo.get_ingestion_logs(limit)
        return {
            "total": len(logs),
            "logs": [
                {
                    "id":         l.id,
                    "sheet_name": l.sheet_name,
                    "nama_orang": l.nama_orang,
                    "total_rows": l.total_rows,
                    "ingested":   l.ingested_count,
                    "failed":     l.failed_count,
                    "status":     l.status,
                    "created_at": l.created_at,
                }
                for l in logs
            ],
        }

    # ------------------------------------------------------------------ #
    #  Private helpers                                                     #
    # ------------------------------------------------------------------ #

    def _fetch_sheet(
        self,
        sheet_url: str,
        sheet_name: Optional[str],
        sheet_index: int,
    ):
        """Fetch sheet dari Google Sheets, wrap exception jadi HTTP 500."""
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
        """Tentukan status ingestion: success / partial / failed."""
        if not errors:
            return "success"
        if ingested_count > 0:
            return "partial"
        return "failed"
