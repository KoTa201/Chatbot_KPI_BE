"""
service/trackerIngestionService.py
...
Changelog v4:
  - Service tidak lagi mengimpor atau membangun SheetIngestionResult / SheetMeta.
    Semua result dikembalikan sebagai plain dict.
    Mapping ke response schema dipindahkan ke KPITrackerController.
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from model.Base import GroupTypeEnum
from model.KPIGroup import KPIGroup
from repository.ingestionLogRepository import IngestionLogRepository
from repository.KpiGroupRepository import KPIGroupRepository
from repository.kpiMasterRepository import KPIMasterRepository
from repository.kpiTrackerRepository import KPITrackerRepository
from schema.kpiTrackerSchema import TrackerSourceItem   # input schema — boleh tetap
from service.googleSheetService import GoogleSheetService
from utils.parser import parse_dataframe
from utils.userLookUp import UserLookupUtil


class TrackerIngestionService:

    def __init__(
        self,
        db:           AsyncSession,
        tracker_repo: KPITrackerRepository | None = None,
        log_repo:     IngestionLogRepository | None = None,
        group_repo:   KPIGroupRepository | None = None,
        master_repo:  KPIMasterRepository | None = None,
    ):
        self.db = db
        self.tracker_repo = tracker_repo or KPITrackerRepository(db)
        self.log_repo = log_repo or IngestionLogRepository(db)
        self.group_repo = group_repo or KPIGroupRepository(db)
        self.master_repo = master_repo or KPIMasterRepository(db)
        self.google_svc = GoogleSheetService()
        self.logger = logging.getLogger(__name__)

        self.strip_fields = {
            "nama_kpi",
            "nama_orang",
            "source_sheet_name",
            "source_sheet_id",
            "document_text",
            "source_row",
            "tahun",
        }

    # ================================================================ #
    #  PUBLIC                                                          #
    # ================================================================ #

    async def ingest_all_sheets(
        self,
        sheet_url:           str,
        nama_orang_override: Optional[str] = None,
        tahun:               int = 2026,
        skip_on_error:       bool = True,
        existing_group_id:   Optional[UUID] = None,
    ) -> dict:
        """
        Returns plain dict — formatting ke schema dilakukan di controller.
        """
        run_log_id: UUID | None = None

        try:
            all_sheets = self._fetch_all_sheets(sheet_url, skip_on_error)
            spreadsheet_id = self._extract_spreadsheet_id(all_sheets)
            effective_tahun = self._resolve_effective_tahun(tahun, all_sheets)
            group = await self._ensure_tracker_group(
                sheet_url, spreadsheet_id, effective_tahun, existing_group_id
            )

            if group:
                run_log = await self.log_repo.create(
                    kpi_group_id=group.id,
                    source_type="tracker",
                    group_name=group.nama_grup,
                )
                run_log_id = run_log.id

            user_lookup = UserLookupUtil(self.db)
            await user_lookup.preload()
            self.logger.info(
                "[TrackerIngestion] User lookup cache: %s", user_lookup.stats()
            )

            sheet_results, totals = await self._process_all_sheets(
                all_sheets=all_sheets,
                sheet_url=sheet_url,
                group=group,
                run_log_id=run_log_id,
                nama_orang_override=nama_orang_override,
                tahun=effective_tahun,
                user_lookup=user_lookup,
            )

            overall_status = self._resolve_status(
                totals.grand_ingested,
                [] if totals.grand_failed == 0 else ["errors"],
            )

            if run_log_id:
                run_errors = [
                    f"{r['sheet_name']}: {r.get('reason') or '; '.join(r.get('errors') or [])}"
                    for r in sheet_results
                    if r["status"] == "failed"
                ]
                await self.log_repo.update_status(
                    log_id=run_log_id,
                    status=overall_status,
                    total_rows=totals.grand_total_rows,
                    ingested_count=totals.grand_ingested,
                    failed_count=totals.grand_failed,
                    errors="; ".join(run_errors) if run_errors else None,
                )

            self.logger.info(
                "[TrackerIngestion] Done: %s/%s records",
                totals.grand_ingested,
                totals.grand_total_rows,
            )

            return {
                "spreadsheet_url":        sheet_url,
                "total_sheets_processed": len(sheet_results),
                "grand_total_rows":       totals.grand_total_rows,
                "grand_ingested":         totals.grand_ingested,
                "grand_failed":           totals.grand_failed,
                "overall_status":         overall_status,
                "sheets":                 sheet_results,   # list[dict]
            }

        except HTTPException:
            if run_log_id:
                await self.log_repo.update_status(
                    log_id=run_log_id,
                    status="failed",
                    errors="HTTPException saat ingestion KPI Tracker.",
                )
            raise

        except Exception as e:
            self.logger.error("[TrackerIngestion] Error: %s", traceback.format_exc())
            if run_log_id:
                await self.log_repo.update_status(
                    log_id=run_log_id, status="failed", errors=str(e)
                )
            raise HTTPException(
                status_code=500,
                detail=f"Error saat ingest KPI Tracker: {str(e)}",
            )

    async def ingest_batch(
        self,
        sources:               list[TrackerSourceItem],
        skip_on_error:         bool = False,
        delay_between_sources: float = 0.0,
    ) -> dict:
        results: list[dict] = []
        grand_total_rows = grand_ingested = grand_failed = 0

        for i, source in enumerate(sources):
            if i > 0 and delay_between_sources > 0:
                self.logger.info(
                    "[TrackerIngestion] Waiting %ss before source %s/%s ...",
                    delay_between_sources, i + 1, len(sources),
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
                results.append({
                    "sheet_url":              url,
                    "status":                 bulk["overall_status"],
                    "total_sheets_processed": bulk["total_sheets_processed"],
                    "grand_total_rows":       bulk["grand_total_rows"],
                    "grand_ingested":         bulk["grand_ingested"],
                    "grand_failed":           bulk["grand_failed"],
                    "sheets":                 bulk["sheets"],
                })
                grand_total_rows += bulk["grand_total_rows"]
                grand_ingested   += bulk["grand_ingested"]
                grand_failed     += bulk["grand_failed"]
            except Exception as exc:
                self.logger.warning(
                    "[TrackerIngestion] Batch failed for url=%r: %s", url, exc
                )
                results.append({"sheet_url": url, "status": "error", "error": str(exc)})

        succeeded = sum(1 for r in results if r.get("status") == "success")
        total_urls = len(sources)
        return {
            "total_urls":       total_urls,
            "succeeded":        succeeded,
            "failed":           total_urls - succeeded,
            "grand_total_rows": grand_total_rows,
            "grand_ingested":   grand_ingested,
            "grand_failed":     grand_failed,
            "results":          results,
        }

    # ================================================================ #
    #  PRIVATE: Bulk helpers                                           #
    # ================================================================ #

    async def _process_all_sheets(
        self,
        all_sheets:          list[dict],
        sheet_url:           str,
        group,
        run_log_id:          Optional[UUID],
        nama_orang_override: Optional[str],
        tahun:               int,
        user_lookup:         UserLookupUtil,
    ) -> tuple[list[dict], "_BulkTotals"]:
        results: list[dict] = []
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
                user_lookup=user_lookup,
            )
            results.append(sheet_result)
            self._accumulate_totals(totals, sheet_result)

        return results, totals

    @staticmethod
    def _build_skipped_sheet_result(sheet: dict) -> dict:
        return {
            "log_id":     None,
            "sheet_name": sheet["sheet_name"],
            "meta":       None,
            "total_rows": None,
            "ingested":   None,
            "failed":     None,
            "errors":     None,
            "status":     "skipped",
            "reason":     sheet["error"],
        }

    @staticmethod
    def _accumulate_totals(totals: "_BulkTotals", sr: dict) -> None:
        totals.grand_total_rows += sr.get("total_rows") or 0
        totals.grand_ingested   += sr.get("ingested") or 0
        totals.grand_failed     += sr.get("failed") or 0

    @staticmethod
    def _extract_spreadsheet_id(all_sheets: list[dict]) -> Optional[str]:
        return next(
            (s["spreadsheet_id"] for s in all_sheets if not s.get("error")),
            None,
        )

    @staticmethod
    def _resolve_effective_tahun(
        requested_tahun: Optional[int],
        all_sheets: list[dict],
    ) -> int:
        if requested_tahun is not None:
            return requested_tahun

        for sheet in all_sheets:
            if sheet.get("error"):
                continue
            meta = sheet.get("meta") or {}
            meta_tahun = meta.get("tahun")
            if meta_tahun is not None:
                return meta_tahun

        return 2026

    async def _ensure_tracker_group(
        self,
        sheet_url:         str,
        spreadsheet_id:    Optional[str],
        tahun:             int,
        existing_group_id: Optional[UUID] = None,
    ):
        if not spreadsheet_id:
            return None

        try:
            nama_grup = self.google_svc.get_spreadsheet_title(sheet_url)
        except Exception:
            nama_grup = "KPI Tracker " + (str(tahun) or "")

        if existing_group_id:
            self.logger.info(
                "[TrackerIngestion] Updating existing KPIGroup id=%s", existing_group_id
            )
            return await self.group_repo.update_committed(
                group_id=existing_group_id,
                fields={
                    "sheet_id":  spreadsheet_id,
                    "sheet_url": sheet_url,
                    "nama_grup": nama_grup,
                    "tahun":     tahun,
                },
            )

        group = await self.group_repo.get_or_create(
            sheet_id=spreadsheet_id,
            group_type="tracker",
            sheet_url=sheet_url,
            sheet_name=None,
            nama_grup=nama_grup,
            tahun=tahun,
        )
        self.logger.info("[TrackerIngestion] KPIGroup ready: group_id=%s", group.id)
        return group

    # ================================================================ #
    #  PRIVATE: Per-sheet pipeline                                     #
    # ================================================================ #

    async def _ingest_single_sheet(
        self,
        sheet:               dict,
        sheet_url:           str,
        group,
        run_log_id:          Optional[UUID],
        nama_orang_override: Optional[str],
        tahun:               int,
        user_lookup:         UserLookupUtil,
    ) -> dict:
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
                return self._sheet_result(
                    context=context,
                    log_id=log_id,
                    total_rows=total_rows,
                    ingested=0,
                    failed=total_rows,
                    errors=["Sheet tidak menghasilkan records valid."],
                    status="failed",
                )

            master_id_map, unmatched_names = await self._match_master_ids(records, context.tahun)
            if unmatched_names:
                extra = [f"KPI '{n}' tidak ditemukan di kpi_master_records" for n in unmatched_names]
                return self._sheet_result(
                    context=context,
                    log_id=log_id,
                    total_rows=total_rows,
                    ingested=0,
                    failed=total_rows,
                    errors=errors + extra,
                    status="failed",
                )

            user_id_map, unresolved_users = await self._resolve_user_ids_for_records(records, user_lookup)
            if unresolved_users:
                extra = [f"User '{n}' tidak ditemukan di tabel users" for n in unresolved_users]
                return self._sheet_result(
                    context=context,
                    log_id=log_id,
                    total_rows=total_rows,
                    ingested=0,
                    failed=total_rows,
                    errors=errors + extra,
                    status="failed",
                )

            clean_records = self._build_clean_records(
                records=records,
                master_id_map=master_id_map,
                user_id_map=user_id_map,
                group_id=group.id if group else None,
                bulan_num=context.bulan_num,
            )

            await self._cleanup_existing_period(group, context.bulan_num)

            ingested_count = await self.tracker_repo.bulk_insert_kpi_records(clean_records)
            status = self._resolve_status(ingested_count, errors)

            return self._sheet_result(
                context=context,
                log_id=log_id,
                total_rows=total_rows,
                ingested=ingested_count,
                failed=total_rows - ingested_count,
                errors=errors,
                status=status,
            )

        except Exception as e:
            self.logger.error(
                "[TrackerIngestion] Error pada sheet '%s': %s", context.sheet_name, str(e)
            )
            return {
                "log_id":     log_id,
                "sheet_name": context.sheet_name,
                "meta":       None,
                "total_rows": None,
                "ingested":   0,
                "failed":     None,
                "errors":     [str(e)],
                "status":     "failed",
                "reason":     None,
            }

    # ================================================================ #
    #  PRIVATE: Result dict builder (satu-satunya titik konstruksi)    #
    # ================================================================ #

    @staticmethod
    def _sheet_result(
        context:    "_SheetContext",
        log_id:     Optional[UUID],
        total_rows: int,
        ingested:   int,
        failed:     int,
        errors:     list[str],
        status:     str,
        reason:     Optional[str] = None,
    ) -> dict:
        """Kembalikan plain dict — bukan schema. Mapping ke schema ada di controller."""
        return {
            "log_id":     log_id,
            "sheet_name": context.sheet_name,
            "meta": {
                "nama_orang": context.nama_orang,
                "bulan_num":  context.bulan_num,
                "tahun":      context.tahun,
            },
            "total_rows": total_rows,
            "ingested":   ingested,
            "failed":     failed,
            "errors":     errors or None,
            "status":     status,
            "reason":     reason,
        }

    # ================================================================ #
    #  PRIVATE: User ID resolution                                     #
    # ================================================================ #

    async def _resolve_user_ids_for_records(
        self,
        records:     list[dict[str, Any]],
        user_lookup: UserLookupUtil,
    ) -> tuple[dict[str, Optional[UUID]], list[str]]:
        unique_names: set[str] = {r["nama_orang"] for r in records if r.get("nama_orang")}
        user_id_map: dict[str, Optional[UUID]] = {}
        unresolved: list[str] = []

        for name in unique_names:
            uid = await user_lookup.by_full_name(name)
            user_id_map[name] = uid
            if uid is None:
                unresolved.append(name)

        self.logger.info(
            "[TrackerIngestion] user_id resolution: %s resolved, %s unresolved.",
            len(unique_names) - len(unresolved),
            len(unresolved),
        )
        return user_id_map, unresolved

    # ================================================================ #
    #  PRIVATE: Record building                                        #
    # ================================================================ #

    def _build_clean_records(
        self,
        records:       list[dict[str, Any]],
        master_id_map: dict[str, UUID],
        user_id_map:   dict[str, Optional[UUID]],
        group_id:      Optional[UUID],
        bulan_num:     Optional[int],
    ) -> list[dict[str, Any]]:
        clean_records: list[dict[str, Any]] = []
        for record in records:
            nama_kpi_val   = record.get("nama_kpi")
            nama_orang_val = record.get("nama_orang")
            clean = {k: v for k, v in record.items() if k not in self.strip_fields}
            clean["bulan_num"]     = bulan_num
            clean["group_id"]      = group_id
            clean["kpi_master_id"] = master_id_map.get(str(nama_kpi_val))
            clean["user_id"]       = user_id_map.get(nama_orang_val) if nama_orang_val else None
            clean_records.append(clean)
        return clean_records

    # ================================================================ #
    #  PRIVATE: KPI Master matching                                    #
    # ================================================================ #

    async def _match_master_ids(
        self,
        records: list[dict[str, Any]],
        tahun:   Optional[int],
    ) -> tuple[dict[str, UUID], list[str]]:
        kpi_names = list({r.get("nama_kpi") for r in records if r.get("nama_kpi")})
        master_id_map = await self._resolve_kpi_master_ids(kpi_names, tahun)
        unmatched = [n for n in kpi_names if n not in master_id_map]
        if unmatched:
            preview = unmatched[:5]
            suffix = "..." if len(unmatched) > 5 else ""
            self.logger.warning(
                "[TrackerIngestion] %s KPI tidak match ke master: %s%s",
                len(unmatched), preview, suffix,
            )
        return master_id_map, unmatched

    async def _resolve_kpi_master_ids(
        self,
        kpi_names: list[str],
        tahun:     Optional[int] = None,
    ) -> dict[str, UUID]:
        if not kpi_names:
            return {}
        try:
            master_map = await self.master_repo.get_id_map_by_names(kpi_names, tahun)
            self.logger.info(
                "[TrackerIngestion] Master matching: %s/%s KPI berhasil di-match",
                len(master_map), len(kpi_names),
            )
            return master_map
        except Exception as e:
            self.logger.error("[TrackerIngestion] Error resolve master IDs: %s", str(e))
            return {}

    # ================================================================ #
    #  PRIVATE: Sheet fetch & parse                                    #
    # ================================================================ #

    def _build_sheet_context(
        self,
        sheet:               dict,
        nama_orang_override: Optional[str],
        tahun:               int,
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

    def _fetch_all_sheets(self, sheet_url: str, skip_on_error: bool) -> list:
        try:
            return self.google_svc.fetch_all_sheets_as_dataframes(
                sheet_url=sheet_url, skip_on_error=skip_on_error
            )
        except HTTPException:
            raise
        except Exception as e:
            err_str = str(e).strip()
            raise HTTPException(
                status_code=500,
                detail=(
                    f"Gagal mengakses spreadsheet: {err_str}"
                    if err_str
                    else f"Gagal mengakses spreadsheet ({type(e).__name__})."
                ),
            )

    def _parse_records(
        self,
        df,
        nama_orang:        str,
        tahun:             Optional[int],
        spreadsheet_id:    str,
        active_sheet_name: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
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

    async def _cleanup_existing_period(
        self,
        group,
        bulan_num: Optional[int],
    ) -> None:
        if not group:
            return
        deleted_count = await self.tracker_repo.delete_kpi_records_by_group_and_period(
            group_id=group.id, bulan_num=bulan_num
        )
        if deleted_count:
            self.logger.info(
                "[TrackerIngestion] Re-ingest cleanup: deleted %s records "
                "for group=%s, bulan_num=%s",
                deleted_count, group.id, bulan_num,
            )

    @staticmethod
    def _resolve_status(ingested_count: int, errors: list) -> str:
        if errors or ingested_count == 0:
            return "failed"
        return "success"


# ──────────────────────────────────────────────────────────────── #
#  Internal dataclasses                                             #
# ──────────────────────────────────────────────────────────────── #

@dataclass
class _SheetContext:
    df:             Any
    meta:           dict[str, Any]
    spreadsheet_id: str
    sheet_name:     str
    nama_orang:     str
    tahun:          Optional[int]
    bulan_num:      Optional[int]


@dataclass
class _BulkTotals:
    grand_total_rows: int = field(default=0)
    grand_ingested:   int = field(default=0)
    grand_failed:     int = field(default=0)
