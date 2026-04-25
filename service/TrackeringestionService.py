"""
service/trackerIngestionService.py
Orchestrator ingestion KPI Tracker dari Google Sheets.

Perbedaan besar dari IngestionService sebelumnya:
  1. KPIGroup auto-created (group_type='tracker') - satu per spreadsheet.
     Jika spreadsheet yang sama di-ingest ulang, grup di-refresh via get_or_create.

  2. IngestionLog pakai IngestionLogRepository (pola dua langkah: create -> update),
     bukan repo.create_ingestion_log() yang ad-hoc.

  3. KPI Master Matching:
     Parser menghasilkan records dengan field 'nama_kpi' (string).
     Sebelum insert, ingestion service meresolve nama_kpi -> kpi_master_id
     dengan query ke kpi_master_records.

  4. Kolom yang di-strip dari records sebelum insert:
      nama_kpi, source_sheet_name, source_sheet_id
      (tidak ada di KPITrackerORM baru).
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIMaster import KPIMasterORM
from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiTrackerRepository import KPITrackerRepository
from schema.kpiTrackerSchema import (
    BatchTrackerIngestionResponse,
    BulkIngestionResponse,
    SheetIngestionResult,
    SheetMeta,
    TrackerSourceItem,
    UrlIngestionResult,
)
from service.googleSheetService import GoogleSheetService
from utils.parser import parse_dataframe


class TrackerIngestionService:
    """
    Orchestrator ingestion KPI Tracker dari Google Sheets.
    Satu instance per request (stateless antar request).
    """

    def __init__(
        self,
        db: AsyncSession,
        tracker_repo: KPITrackerRepository,
        log_repo: IngestionLogRepository,
        group_repo: KPIGroupRepository,
    ):
        self.db = db
        self.tracker_repo = tracker_repo
        self.log_repo = log_repo
        self.group_repo = group_repo
        self.google_svc = GoogleSheetService()
        self.logger = logging.getLogger(__name__)
        self.strip_fields = {"nama_kpi", "source_sheet_name", "source_sheet_id",
                             "document_text", "source_row"}

    # ================================================================ #
    #  PUBLIC: Entry point                                             #
    # ================================================================ #

    async def ingest_all_sheets(
        self,
        sheet_url: str,
        nama_orang_override: str = None,
        tahun: int = 2026,
        skip_on_error: bool = True,
    ) -> BulkIngestionResponse:
        """
        Ingest semua tab dalam satu spreadsheet.

        Side effects (otomatis):
          - KPIGroup di-upsert (satu per spreadsheet)
          - IngestionLog dibuat dan diupdate per tab

        Returns:
            BulkIngestionResponse dengan agregasi per-tab + grand total.
        """
        run_log_id: UUID | None = None
        try:
            all_sheets = self._fetch_all_sheets(sheet_url, skip_on_error)
            spreadsheet_id = self._extract_spreadsheet_id(all_sheets)
            group = await self._ensure_tracker_group(sheet_url, spreadsheet_id, tahun)

            if group:
                run_log = await self.log_repo.create(kpi_group_id=group.id)
                run_log_id = run_log.id

            sheets_result, totals = await self._process_all_sheets(
                all_sheets=all_sheets,
                sheet_url=sheet_url,
                group=group,
                run_log_id=run_log_id,
                nama_orang_override=nama_orang_override,
                tahun=tahun,
            )

            overall_status = self._resolve_status(
                totals.grand_ingested,
                [] if totals.grand_failed == 0 else ["errors"],
            )

            if run_log_id:
                run_errors = [
                    f"{r.sheet_name}: {r.reason or '; '.join(r.errors or [])}"
                    for r in sheets_result
                    if r.status == "failed"
                ]
                await self.log_repo.update_status(
                    log_id=run_log_id,
                    status=overall_status,
                    total_rows=totals.grand_total_rows,
                    ingested_count=totals.grand_ingested,
                    failed_count=totals.grand_failed,
                    errors=self._format_errors(
                        run_errors) if run_errors else None,
                )

            self.logger.info(
                "[TrackerIngestion] Done: %s/%s records",
                totals.grand_ingested,
                totals.grand_total_rows,
            )

            return BulkIngestionResponse(
                spreadsheet_url=sheet_url,
                total_sheets_processed=len(sheets_result),
                grand_total_rows=totals.grand_total_rows,
                grand_ingested=totals.grand_ingested,
                grand_failed=totals.grand_failed,
                overall_status=overall_status,
                sheets=sheets_result,
            )

        except HTTPException:
            if run_log_id:
                await self.log_repo.update_status(
                    log_id=run_log_id,
                    status="failed",
                    errors="HTTPException saat ingestion KPI Tracker.",
                )
            raise
        except Exception as e:
            self.logger.error("[TrackerIngestion] Error: %s",
                              traceback.format_exc())
            if run_log_id:
                await self.log_repo.update_status(
                    log_id=run_log_id,
                    status="failed",
                    errors=str(e),
                )
            raise HTTPException(
                status_code=500,
                detail=f"Error saat ingest KPI Tracker: {str(e)}",
            )

    async def ingest_batch(
        self,
        sources: list[TrackerSourceItem],
        skip_on_error: bool = True,
        delay_between_sources: float = 0.0,
    ) -> BatchTrackerIngestionResponse:
        """
        Ingest beberapa spreadsheet sekaligus.
        Setiap source membawa sheet_url + tahun masing-masing.
        Gagalnya satu URL tidak menghentikan URL lain.

        Args:
            delay_between_sources: Jeda (detik) antar ingest spreadsheet.
                Berguna untuk menghindari rate limit Google Sheets API (maks 6 req/menit).
                Contoh: delay_between_sources=10.0 -> jeda 10 detik antar spreadsheet.
        """
        results: list[UrlIngestionResult] = []
        grand_total_rows = 0
        grand_ingested = 0
        grand_failed = 0

        for i, source in enumerate(sources):
            if i > 0 and delay_between_sources > 0:
                self.logger.info(
                    "[TrackerIngestion] Menunggu %ss sebelum ingest source ke-%s...",
                    delay_between_sources,
                    i + 1,
                )
                await asyncio.sleep(delay_between_sources)

            url = source.sheet_url
            tahun = source.tahun
            try:
                bulk = await self.ingest_all_sheets(
                    sheet_url=url,
                    tahun=tahun,
                    skip_on_error=skip_on_error,
                )
                results.append(
                    UrlIngestionResult(
                        sheet_url=url,
                        status=bulk.overall_status,
                        total_sheets_processed=bulk.total_sheets_processed,
                        grand_total_rows=bulk.grand_total_rows,
                        grand_ingested=bulk.grand_ingested,
                        grand_failed=bulk.grand_failed,
                        sheets=bulk.sheets,
                    )
                )
                grand_total_rows += bulk.grand_total_rows
                grand_ingested += bulk.grand_ingested
                grand_failed += bulk.grand_failed
            except Exception as exc:
                self.logger.warning(
                    "[TrackerIngestion] Batch: failed for url=%r: %s",
                    url,
                    exc,
                )
                results.append(
                    UrlIngestionResult(
                        sheet_url=url,
                        status="error",
                        error=str(exc),
                    )
                )

        succeeded = sum(1 for r in results if r.status == "success")
        total_urls = len(sources)

        return BatchTrackerIngestionResponse(
            total_urls=total_urls,
            succeeded=succeeded,
            failed=total_urls - succeeded,
            grand_total_rows=grand_total_rows,
            grand_ingested=grand_ingested,
            grand_failed=grand_failed,
            results=results,
        )

    # ================================================================ #
    #  PRIVATE: Bulk helpers                                           #
    # ================================================================ #

    async def _process_all_sheets(
        self,
        all_sheets: list[dict],
        sheet_url: str,
        group,
        run_log_id: Optional[UUID],
        nama_orang_override: Optional[str],
        tahun: int,
    ) -> tuple[list[SheetIngestionResult], "_BulkTotals"]:
        results: list[SheetIngestionResult] = []
        totals = _BulkTotals()

        for sheet in all_sheets:
            if sheet.get("error"):
                results.append(self._build_skipped_sheet_result(sheet))
                continue

            sheet_result = await self._ingest_single_sheet(
                sheet=sheet,
                sheet_url=sheet_url,
                group=group,
                run_log_id=run_log_id,
                nama_orang_override=nama_orang_override,
                tahun=tahun,
            )
            results.append(sheet_result)
            self._accumulate_totals(totals, sheet_result)

        return results, totals

    def _build_skipped_sheet_result(self, sheet: dict) -> SheetIngestionResult:
        return SheetIngestionResult(
            log_id=None,
            sheet_name=sheet["sheet_name"],
            meta=None,
            total_rows=None,
            ingested=None,
            failed=None,
            errors=None,
            status="skipped",
            reason=sheet["error"],
        )

    @staticmethod
    def _accumulate_totals(totals: "_BulkTotals", sheet_result: SheetIngestionResult) -> None:
        totals.grand_total_rows += sheet_result.total_rows or 0
        totals.grand_ingested += sheet_result.ingested or 0
        totals.grand_failed += sheet_result.failed or 0

    @staticmethod
    def _extract_spreadsheet_id(all_sheets: list[dict]) -> Optional[str]:
        return next(
            (s["spreadsheet_id"] for s in all_sheets if not s.get("error")),
            None,
        )

    async def _ensure_tracker_group(self, sheet_url: str, spreadsheet_id: Optional[str], tahun: int):
        if not spreadsheet_id:
            return None

        self.logger.info(
            "[TrackerIngestion] Upserting KPIGroup for spreadsheet_id=%s",
            spreadsheet_id,
        )

        try:
            nama_grup = self.google_svc.get_spreadsheet_title(sheet_url)
        except Exception:
            nama_grup = "KPI Tracker " + (str(tahun) or "")

        group = await self.group_repo.get_or_create(
            sheet_id=spreadsheet_id,
            group_type="tracker",
            sheet_url=sheet_url,
            sheet_name=None,
            nama_grup=nama_grup,
            tahun=tahun,
        )

        self.logger.info(
            "[TrackerIngestion] KPIGroup ready: group_id=%s", group.id)
        return group

    # ================================================================ #
    #  PRIVATE: Per-sheet pipeline                                    #
    # ================================================================ #

    async def _ingest_single_sheet(
        self,
        sheet: dict,
        sheet_url: str,
        group,
        run_log_id: Optional[UUID],
        nama_orang_override: Optional[str],
        tahun: int,
    ) -> SheetIngestionResult:
        """
        Pipeline ingestion untuk satu tab sheet.
        Log dikelola di level ingest spreadsheet (bukan per tab).
        """
        del sheet_url

        context = self._build_sheet_context(sheet, nama_orang_override, tahun)
        log_id = run_log_id

        try:
            records, errors = self._parse_records(
                df=context.df,
                nama_orang=context.nama_orang,
                tahun=context.tahun,
                spreadsheet_id=context.spreadsheet_id,
                active_sheet_name=context.sheet_name,
            )

            total_rows = len(context.df)
            if not records:
                return await self._build_failed_no_records_result(
                    context=context,
                    total_rows=total_rows,
                    log_id=log_id,
                )

            master_id_map, unmatched_names = await self._match_master_ids(
                records=records,
                tahun=context.tahun,
            )
            if unmatched_names:
                return await self._build_failed_unmatched_master_result(
                    context=context,
                    total_rows=total_rows,
                    errors=errors,
                    unmatched_names=unmatched_names,
                    log_id=log_id,
                )

            clean_records = self._build_clean_records(
                records=records,
                master_id_map=master_id_map,
                group_id=group.id if group else None,
                tahun=context.tahun,
                bulan_num=context.bulan_num,
            )

            await self._cleanup_existing_period(
                group=group,
                tahun=context.tahun,
                bulan_num=context.bulan_num,
            )

            ingested_count = await self.tracker_repo.bulk_insert_kpi_records(clean_records)
            return await self._finalize_success_result(
                context=context,
                total_rows=total_rows,
                ingested_count=ingested_count,
                errors=errors,
                log_id=log_id,
            )

        except Exception as e:
            self.logger.error(
                "[TrackerIngestion] Error pada sheet '%s': %s",
                context.sheet_name,
                str(e),
            )
            return SheetIngestionResult(
                log_id=log_id,
                sheet_name=context.sheet_name,
                meta=None,
                total_rows=None,
                ingested=0,
                failed=None,
                errors=[str(e)],
                status="failed",
            )

    def _build_sheet_context(
        self,
        sheet: dict,
        nama_orang_override: Optional[str],
        tahun: int,
    ) -> "_SheetContext":
        meta = sheet["meta"]
        nama_orang = nama_orang_override or meta.get("nama_orang") or "UNKNOWN"
        final_tahun = tahun or meta.get("tahun")

        return _SheetContext(
            df=sheet["df"],
            meta=meta,
            spreadsheet_id=sheet["spreadsheet_id"],
            sheet_name=sheet["sheet_name"],
            nama_orang=nama_orang,
            tahun=final_tahun,
            bulan_num=meta.get("bulan_num") if meta else None,
        )

    async def _build_failed_no_records_result(
        self,
        context: "_SheetContext",
        total_rows: int,
        log_id: Optional[UUID] = None,
    ) -> SheetIngestionResult:
        return SheetIngestionResult(
            log_id=log_id,
            sheet_name=context.sheet_name,
            meta=self._build_sheet_meta(context),
            total_rows=total_rows,
            ingested=0,
            failed=total_rows,
            errors=["Tidak ada records valid."],
            status="failed",
        )

    async def _match_master_ids(
        self,
        records: list[dict[str, Any]],
        tahun: Optional[int],
    ) -> tuple[dict[str, UUID], list[str]]:
        kpi_names = list({r.get("nama_kpi")
                         for r in records if r.get("nama_kpi")})
        master_id_map = await self._resolve_kpi_master_ids(kpi_names, tahun)
        unmatched_names = [
            name for name in kpi_names if name not in master_id_map]

        if unmatched_names:
            preview = unmatched_names[:5]
            suffix = "..." if len(unmatched_names) > 5 else ""
            self.logger.warning(
                "[TrackerIngestion] %s KPI tidak match ke master: %s%s",
                len(unmatched_names),
                preview,
                suffix,
            )

        return master_id_map, unmatched_names

    async def _build_failed_unmatched_master_result(
        self,
        context: "_SheetContext",
        total_rows: int,
        errors: list[str],
        unmatched_names: list[str],
        log_id: Optional[UUID] = None,
    ) -> SheetIngestionResult:
        errors.extend(
            [f"KPI '{name}' tidak ditemukan di kpi_master_records" for name in unmatched_names]
        )

        return SheetIngestionResult(
            log_id=log_id,
            sheet_name=context.sheet_name,
            meta=self._build_sheet_meta(context),
            total_rows=total_rows,
            ingested=0,
            failed=total_rows,
            errors=errors,
            status="failed",
        )

    def _build_clean_records(
        self,
        records: list[dict[str, Any]],
        master_id_map: dict[str, UUID],
        group_id: Optional[UUID],
        tahun: Optional[int],
        bulan_num: Optional[int],
    ) -> list[dict[str, Any]]:
        clean_records: list[dict[str, Any]] = []

        for record in records:
            nama_kpi_val = record.get("nama_kpi")
            clean = {k: v for k, v in record.items(
            ) if k not in self.strip_fields}
            clean["tahun"] = clean.get("tahun") or tahun
            clean["bulan_num"] = bulan_num
            clean["group_id"] = group_id
            clean["kpi_master_id"] = master_id_map.get(nama_kpi_val)
            clean_records.append(clean)

        return clean_records

    async def _cleanup_existing_period(
        self,
        group,
        tahun: Optional[int],
        bulan_num: Optional[int],
    ) -> None:
        if not group or not tahun:
            return

        deleted_count = await self.tracker_repo.delete_kpi_records_by_group_and_period(
            group_id=group.id,
            tahun=tahun,
            bulan_num=bulan_num,
        )
        if deleted_count:
            self.logger.info(
                "[TrackerIngestion] Re-ingest cleanup: deleted %s records "
                "for group=%s, tahun=%s, bulan_num=%s",
                deleted_count,
                group.id,
                tahun,
                bulan_num,
            )

    async def _finalize_success_result(
        self,
        context: "_SheetContext",
        total_rows: int,
        ingested_count: int,
        errors: list[str],
        log_id: Optional[UUID] = None,
    ) -> SheetIngestionResult:
        status = self._resolve_status(ingested_count, errors)

        return SheetIngestionResult(
            log_id=log_id,
            sheet_name=context.sheet_name,
            meta=self._build_sheet_meta(context),
            total_rows=total_rows,
            ingested=ingested_count,
            failed=total_rows - ingested_count,
            errors=errors,
            status=status,
        )

    @staticmethod
    def _build_sheet_meta(context: "_SheetContext") -> SheetMeta:
        return SheetMeta(
            nama_orang=context.nama_orang,
            bulan_num=context.bulan_num,
            tahun=context.tahun,
        )

    # ================================================================ #
    #  PRIVATE: KPI Master Matching                                    #
    # ================================================================ #

    async def _resolve_kpi_master_ids(
        self,
        kpi_names: list[str],
        tahun: Optional[int] = None,
    ) -> dict[str, UUID]:
        """
        Resolve nama_kpi (string) -> kpi_master_id (UUID).

        Query ke kpi_master_records WHERE kpi_name IN (...).
        Jika tahun disediakan, filter juga by tahun agar tidak terjadi
        ambiguitas jika nama KPI sama di tahun berbeda.

        Returns:
            {kpi_name: UUID} - hanya berisi yang ditemukan.
            Nama yang tidak ditemukan tidak masuk dict (caller handle sebagai None).
        """
        if not kpi_names:
            return {}

        try:
            query = select(KPIMasterORM.id, KPIMasterORM.kpi_name).where(
                KPIMasterORM.kpi_name.in_(kpi_names)
            )
            if tahun:
                query = query.where(KPIMasterORM.tahun == tahun)

            result = await self.db.execute(query)
            rows = result.fetchall()

            master_map: dict[str, UUID] = {}
            for row in rows:
                if row.kpi_name not in master_map:
                    master_map[row.kpi_name] = row.id
                else:
                    self.logger.warning(
                        "[TrackerIngestion] Duplikasi kpi_name='%s' di kpi_master_records. "
                        "Gunakan filter tahun untuk presisi.",
                        row.kpi_name,
                    )

            self.logger.info(
                "[TrackerIngestion] Master matching: %s/%s KPI berhasil di-match",
                len(master_map),
                len(kpi_names),
            )
            return master_map

        except Exception as e:
            self.logger.error(
                "[TrackerIngestion] Error resolve master IDs: %s", str(e))
            return {}

    # ================================================================ #
    #  PRIVATE: Helpers                                                #
    # ================================================================ #

    def _fetch_all_sheets(self, sheet_url: str, skip_on_error: bool) -> list:
        try:
            return self.google_svc.fetch_all_sheets_as_dataframes(
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

    def _parse_records(
        self,
        df,
        nama_orang: str,
        tahun: Optional[int],
        spreadsheet_id: str,
        active_sheet_name: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Parse DataFrame -> (records, errors).
        Records masih memiliki 'nama_kpi' - akan di-resolve ke kpi_master_id
        dan di-strip oleh caller (_ingest_single_sheet).
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
            raise HTTPException(status_code=422, detail=str(e))

    @staticmethod
    def _resolve_status(ingested_count: int, errors: list) -> str:
        if errors or ingested_count == 0:
            return "failed"
        return "success"

    @staticmethod
    def _format_errors(errors: list, max_errors: int = 20) -> str:
        summary = errors[:max_errors]
        result = "; ".join(str(e) for e in summary)
        if len(errors) > max_errors:
            result += f" ... dan {len(errors) - max_errors} error lainnya."
        return result


@dataclass
class _SheetContext:
    df: Any
    meta: dict[str, Any]
    spreadsheet_id: str
    sheet_name: str
    nama_orang: str
    tahun: Optional[int]
    bulan_num: Optional[int]


@dataclass
class _BulkTotals:
    grand_total_rows: int = 0
    grand_ingested: int = 0
    grand_failed: int = 0
