"""
service/trackerIngestionService.py
Orchestrator ingestion KPI Tracker dari Google Sheets.

Perbedaan besar dari IngestionService sebelumnya:
  1. KPIGroup auto-created (group_type='tracker') — satu per spreadsheet.
     Jika spreadsheet yang sama di-ingest ulang, grup di-refresh via get_or_create.

  2. IngestionLog pakai IngestionLogRepository (pola dua langkah: create → update),
     bukan repo.create_ingestion_log() yang ad-hoc.

  3. KPI Master Matching (langkah BARU):
     Parser masih menghasilkan records dengan field 'nama_kpi' (string).
     Sebelum insert, ingestion service meresolve nama_kpi → kpi_master_id
     dengan query ke kpi_master_records.
     Records yang tidak bisa di-match tetap disimpan dengan kpi_master_id=None.

  4. Kolom yang di-strip dari records sebelum insert:
      nama_kpi, source_sheet_name, source_sheet_id
      (tidak ada di KPITrackerORM baru).

Alur per-sheet:
  sheet_url
    → get_or_create KPIGroup (per spreadsheet, bukan per tab)
    → create IngestionLog(running)
    → fetch + parse sheet → records{nama_kpi, realisasi, nama_orang, ...}
    → _resolve_kpi_master_ids(nama_kpi list) → {nama_kpi: UUID}
    → inject group_id, kpi_master_id; strip kolom lama
    → bulk_insert
    → update_status IngestionLog
"""

import logging
import traceback
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.Base import IngestionSourceType
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
from service.kpiTrackerService import KPITrackerService
from utils.parser import parse_dataframe

logger = logging.getLogger(__name__)

# Kolom dari parser lama yang tidak ada di model baru — harus di-strip sebelum insert
_STRIP_FIELDS = {"nama_kpi", "source_sheet_name", "source_sheet_id"}


class TrackerIngestionService:
    """
    Orchestrator ingestion KPI Tracker dari Google Sheets.
    Satu instance per request (stateless antar request).
    """

    def __init__(
        self,
        db:           AsyncSession,
        tracker_repo: KPITrackerRepository,
        tracker_svc:  KPITrackerService,
        log_repo:     IngestionLogRepository,
        group_repo:   KPIGroupRepository,
    ):
        self.db = db
        self.tracker_repo = tracker_repo
        self.tracker_svc = tracker_svc
        self.log_repo = log_repo
        self.group_repo = group_repo
        self.google_svc = GoogleSheetService()

    # ================================================================ #
    #  PUBLIC: Entry point                                              #
    # ================================================================ #

    async def ingest_all_sheets(
        self,
        sheet_url:           str,
        nama_orang_override: str = None,
        tahun: int = 2026,
        skip_on_error:       bool = True,
    ) -> BulkIngestionResponse:
        """
        Ingest semua tab dalam satu spreadsheet.

        Side effects (otomatis):
          - KPIGroup di-upsert (satu per spreadsheet)
          - IngestionLog dibuat dan diupdate per tab

        Returns:
            BulkIngestionResponse dengan agregasi per-tab + grand total.
        """
        try:
            all_sheets = self._fetch_all_sheets(sheet_url, skip_on_error)

            sheets_result: List[SheetIngestionResult] = []
            grand_total_rows = 0
            grand_ingested = 0
            grand_failed = 0

            # spreadsheet_id sama untuk semua tab — ambil dari sheet pertama
            spreadsheet_id = next(
                (s["spreadsheet_id"]
                 for s in all_sheets if not s.get("error")),
                None,
            )

            # ── STEP 1: Auto-create KPIGroup per spreadsheet ─────────
            # Satu spreadsheet = satu grup tracker, shared oleh semua tab-nya.
            group = None
            if spreadsheet_id:
                logger.info(
                    f"[TrackerIngestion] Upserting KPIGroup for spreadsheet_id={spreadsheet_id}"
                )
                # Nama grup = judul spreadsheet di Google Drive
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
                logger.info(
                    f"[TrackerIngestion] KPIGroup ready: group_id={group.id}"
                )

            # ── STEP 2: Proses per tab ────────────────────────────────
            for sheet in all_sheets:
                if sheet.get("error"):
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

                sheet_result = await self._ingest_single_sheet(
                    sheet=sheet,
                    sheet_url=sheet_url,
                    group=group,
                    nama_orang_override=nama_orang_override,
                    tahun=tahun,
                )

                sheets_result.append(sheet_result)
                grand_total_rows += sheet_result.total_rows or 0
                grand_ingested += sheet_result.ingested or 0
                grand_failed += sheet_result.failed or 0

            overall_status = self._resolve_status(
                grand_ingested,
                [] if grand_failed == 0 else ["errors"],
            )

            logger.info(
                f"[TrackerIngestion] Done: {grand_ingested}/{grand_total_rows} records"
            )

            return BulkIngestionResponse(
                spreadsheet_url=sheet_url,
                total_sheets_processed=len(sheets_result),
                grand_total_rows=grand_total_rows,
                grand_ingested=grand_ingested,
                grand_failed=grand_failed,
                overall_status=overall_status,
                sheets=sheets_result,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[TrackerIngestion] Error: {traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error saat ingest KPI Tracker: {str(e)}",
            )

    async def ingest_batch(
        self,
        sources: list[TrackerSourceItem],
        skip_on_error: bool = True,
    ) -> BatchTrackerIngestionResponse:
        """
        Ingest beberapa spreadsheet sekaligus.
        Setiap source membawa sheet_url + tahun masing-masing.
        Gagalnya satu URL tidak menghentikan URL lain.
        """
        results: list[UrlIngestionResult] = []
        grand_total_rows = 0
        grand_ingested = 0
        grand_failed = 0

        for source in sources:
            url = source.sheet_url
            tahun = source.tahun
            try:
                bulk = await self.ingest_all_sheets(
                    sheet_url=url,
                    tahun=tahun,
                    skip_on_error=skip_on_error,
                )
                results.append(UrlIngestionResult(
                    sheet_url=url,
                    status=bulk.overall_status,
                    total_sheets_processed=bulk.total_sheets_processed,
                    grand_total_rows=bulk.grand_total_rows,
                    grand_ingested=bulk.grand_ingested,
                    grand_failed=bulk.grand_failed,
                    sheets=bulk.sheets,
                ))
                grand_total_rows += bulk.grand_total_rows
                grand_ingested += bulk.grand_ingested
                grand_failed += bulk.grand_failed
            except Exception as exc:
                logger.warning(
                    f"[TrackerIngestion] Batch: failed for url={url!r}: {exc}"
                )
                results.append(UrlIngestionResult(
                    sheet_url=url,
                    status="error",
                    error=str(exc),
                ))

        succeeded = sum(
            1 for r in results if r.status == "success"
        )
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
    #  PRIVATE: Per-sheet pipeline                                     #
    # ================================================================ #

    async def _ingest_single_sheet(
        self,
        sheet:               dict,
        sheet_url:           str,
        group,               # KPIGroupORM | None
        nama_orang_override: Optional[str],
        tahun: int,
    ) -> SheetIngestionResult:
        """
        Pipeline ingestion untuk satu tab sheet.
        Log dibuat di awal (status=running) dan diupdate di akhir.
        """
        df = sheet["df"]
        meta = sheet["meta"]
        spreadsheet_id = sheet["spreadsheet_id"]
        active_sheet_name = sheet["sheet_name"]

        nama_orang = nama_orang_override or meta.get("nama_orang") or "UNKNOWN"
        tahun = tahun or meta.get("tahun")
        log_id = None

        try:
            # Create IngestionLog (running) — sebelum proses dimulai
            log = await self.log_repo.create(
                source_type=IngestionSourceType.KPI_TRACKER,
                source_id=group.id if group else None,
                sheet_url=sheet_url,
                sheet_id=spreadsheet_id,
                sheet_name=active_sheet_name,
            )
            log_id = log.id

            # Parse DataFrame → records masih punya nama_kpi (string)
            records, errors = self._parse_records(
                df=df,
                nama_orang=nama_orang,
                tahun=tahun,
                spreadsheet_id=spreadsheet_id,
                active_sheet_name=active_sheet_name,
            )

            total_rows = len(df)

            if not records:
                await self.log_repo.update_status(
                    log_id=log_id,
                    status="failed",
                    total_rows=total_rows,
                    errors="Tidak ada records valid setelah parsing.",
                )
                return SheetIngestionResult(
                    log_id=log_id,
                    sheet_name=active_sheet_name,
                    meta=SheetMeta(
                        nama_orang=nama_orang,
                        bulan=meta.get("bulan"),
                        bulan_num=meta.get("bulan_num"),
                        tahun=tahun,
                    ),
                    total_rows=total_rows,
                    ingested=0,
                    failed=total_rows,
                    errors=["Tidak ada records valid."],
                    status="failed",
                )

            # ── KPI Master Matching (langkah BARU) ───────────────────
            # nama_kpi string → kpi_master_id UUID
            # Records yang tidak match tetap disimpan (kpi_master_id=None)
            kpi_names = list({r.get("nama_kpi")
                             for r in records if r.get("nama_kpi")})
            master_id_map = await self._resolve_kpi_master_ids(kpi_names, tahun)

            unmatched_names = [n for n in kpi_names if n not in master_id_map]
            if unmatched_names:
                logger.warning(
                    f"[TrackerIngestion] {len(unmatched_names)} KPI tidak match ke master: "
                    f"{unmatched_names[:5]}{'...' if len(unmatched_names) > 5 else ''}"
                )
                errors.extend([
                    f"KPI '{n}' tidak ditemukan di kpi_master_records" for n in unmatched_names
                ])

                # Strict mode: jika ada KPI yang tidak match ke master,
                # seluruh sheet dianggap gagal dan tidak ada data yang diinsert.
                error_str = self._format_errors(errors)
                await self.log_repo.update_status(
                    log_id=log_id,
                    status="failed",
                    total_rows=total_rows,
                    ingested_count=0,
                    failed_count=total_rows,
                    errors=error_str,
                )

                return SheetIngestionResult(
                    log_id=log_id,
                    sheet_name=active_sheet_name,
                    meta=SheetMeta(
                        nama_orang=nama_orang,
                        bulan=meta.get("bulan"),
                        bulan_num=meta.get("bulan_num"),
                        tahun=tahun,
                    ),
                    total_rows=total_rows,
                    ingested=0,
                    failed=total_rows,
                    errors=errors,
                    status="failed",
                )

            # Inject group_id + kpi_master_id + bulan, strip kolom lama
            bulan = meta.get("bulan") if meta else None
            bulan_num = meta.get("bulan_num") if meta else None
            clean_records = []
            for record in records:
                nama_kpi_val = record.get("nama_kpi")
                clean = {k: v for k, v in record.items()
                         if k not in _STRIP_FIELDS}
                # Tahun wajib non-null di model; fallback ke konteks ingest.
                clean["tahun"] = clean.get("tahun") or tahun
                clean["bulan"] = bulan
                clean["bulan_num"] = bulan_num
                clean["group_id"] = group.id if group else None
                clean["kpi_master_id"] = master_id_map.get(
                    nama_kpi_val)  # None jika unmatched
                clean_records.append(clean)

            # Idempotent ingest: re-ingest periode yang sama replace data lama.
            if group and tahun:
                deleted_count = await self.tracker_repo.delete_kpi_records_by_group_and_period(
                    group_id=group.id,
                    tahun=tahun,
                    bulan_num=bulan_num,
                )
                if deleted_count:
                    logger.info(
                        f"[TrackerIngestion] Re-ingest cleanup: deleted {deleted_count} "
                        f"records for group={group.id}, tahun={tahun}, bulan_num={bulan_num}"
                    )

            # Bulk insert via service (validasi group_id ada)
            ingested_result = await self.tracker_svc.bulk_create_records(clean_records)
            ingested_count = ingested_result.get("count", 0)

            status = self._resolve_status(ingested_count, errors)
            error_str = self._format_errors(errors) if errors else None

            await self.log_repo.update_status(
                log_id=log_id,
                status=status,
                total_rows=total_rows,
                ingested_count=ingested_count,
                failed_count=total_rows - ingested_count,
                errors=error_str,
            )

            return SheetIngestionResult(
                log_id=log_id,
                sheet_name=active_sheet_name,
                meta=SheetMeta(
                    nama_orang=nama_orang,
                    bulan=meta.get("bulan"),
                    bulan_num=meta.get("bulan_num"),
                    tahun=tahun,
                ),
                total_rows=total_rows,
                ingested=ingested_count,
                failed=total_rows - ingested_count,
                errors=errors,
                status=status,
            )

        except Exception as e:
            logger.error(
                f"[TrackerIngestion] Error pada sheet '{active_sheet_name}': {str(e)}"
            )
            if log_id:
                await self._mark_log_failed(log_id, str(e))
            return SheetIngestionResult(
                log_id=log_id,
                sheet_name=active_sheet_name,
                meta=None,
                total_rows=None,
                ingested=0,
                failed=None,
                errors=[str(e)],
                status="failed",
            )

    # ================================================================ #
    #  PRIVATE: KPI Master Matching                                    #
    # ================================================================ #

    async def _resolve_kpi_master_ids(
        self,
        kpi_names: list[str],
        tahun:     Optional[int] = None,
    ) -> Dict[str, UUID]:
        """
        Resolve nama_kpi (string) → kpi_master_id (UUID).

        Query ke kpi_master_records WHERE kpi_name IN (...).
        Jika tahun disediakan, filter juga by tahun agar tidak terjadi
        ambiguitas jika nama KPI sama di tahun berbeda.

        Returns:
            {kpi_name: UUID} — hanya berisi yang ditemukan.
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

            # Jika ada duplikasi nama KPI (beda tahun, filter tahun tidak aktif),
            # ambil yang pertama ditemukan — warning di log.
            master_map: Dict[str, UUID] = {}
            for row in rows:
                if row.kpi_name not in master_map:
                    master_map[row.kpi_name] = row.id
                else:
                    logger.warning(
                        f"[TrackerIngestion] Duplikasi kpi_name='{row.kpi_name}' "
                        "di kpi_master_records. Gunakan filter tahun untuk presisi."
                    )

            logger.info(
                f"[TrackerIngestion] Master matching: "
                f"{len(master_map)}/{len(kpi_names)} KPI berhasil di-match"
            )
            return master_map

        except Exception as e:
            logger.error(
                f"[TrackerIngestion] Error resolve master IDs: {str(e)}")
            # Jangan gagalkan seluruh ingestion hanya karena matching error
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
        nama_orang:        str,
        tahun:             Optional[int],
        spreadsheet_id:    str,
        active_sheet_name: str,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Parse DataFrame → (records, errors).
        Records masih memiliki 'nama_kpi' — akan di-resolve ke kpi_master_id
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

    async def _mark_log_failed(self, log_id: UUID, reason: str) -> None:
        try:
            await self.log_repo.update_status(
                log_id=log_id,
                status="failed",
                errors=reason,
            )
        except Exception:
            logger.warning(
                f"[TrackerIngestion] Gagal update log {log_id} ke 'failed'"
            )
