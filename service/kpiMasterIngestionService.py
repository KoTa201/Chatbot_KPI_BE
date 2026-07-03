"""
service/kpiMasterIngestionService.py
Orchestrator ingestion KPI Master dari Google Sheets.

Changelog v4 (many-to-many):
  - _inject_user_ids() kini menggunakan UserLookupUtil.all_ids_in_text()
    sehingga SEMUA nama di responsibility_persons (comma-separated) di-resolve
    ke list[UUID], bukan hanya nama pertama.
  - Record menerima key "user_ids" (list[UUID]) sebagai pengganti "user_id".
  - Repository upsert_by_group() mengelola sync ke junction table
    kpi_master_users secara otomatis.
  - Perilaku unresolved: sama seperti v3
      * ingest_kpi_master  → fail (HTTP 422) jika ada nama tidak ditemukan.
      * update_and_reingest → lenient; nama yang tidak ditemukan dicatat di log.

Alur "trigger-like" saat ingest:
  1. KPIGroup di-upsert berdasarkan sheet_id.
  2. IngestionLog dibuat dengan status 'running'.
  3. Records di-parse dan di-inject dengan group_id.
  4. user_ids di-resolve untuk setiap record (batch, dengan cache).
  5. KPI Master di-upsert + junction table di-sync.
  6. IngestionLog di-update ke status akhir.
"""

import logging
import traceback
from typing import Optional
from uuid import UUID

from fastapi import HTTPException

from exceptions import (
    AppError,
    BadRequestError,
    InternalError,
    NotFoundError,
    ValidationError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from repository.ingestionLogRepository import IngestionLogRepository
from repository.kpiGroupRepository import KPIGroupRepository
from repository.kpiMasterRepository import KPIMasterRepository
from service.columnStatisticsService import ColumnStatisticsService
from service.kpiMasterService import KPIMasterService
from utils.userLookUp import UserLookupUtil

logger = logging.getLogger(__name__)


class KPIMasterIngestionService:

    def __init__(
        self,
        db:          AsyncSession,
        kpi_repo:    KPIMasterRepository | None = None,
        kpi_service: KPIMasterService | None = None,
        log_repo:    IngestionLogRepository | None = None,
        group_repo:  KPIGroupRepository | None = None,
    ):
        self.db: AsyncSession = db
        self.kpi_repo: KPIMasterRepository = kpi_repo or KPIMasterRepository(db)
        self.kpi_service: KPIMasterService = kpi_service or KPIMasterService(repository=self.kpi_repo)
        self.log_repo: IngestionLogRepository = log_repo or IngestionLogRepository(db)
        self.group_repo: KPIGroupRepository = group_repo or KPIGroupRepository(db)

    # ================================================================ #
    #  PUBLIC: Entry point ingestion                                    #
    # ================================================================ #

    async def ingest_kpi_master(
        self,
        sheet_url: str,
        tahun:     int,
    ) -> dict:
        """
        Ingest KPI Master dari Google Sheets.

        Side effects (otomatis, tanpa input dari caller):
          - KPIGroup di-upsert.
          - IngestionLog dibuat dan diupdate.
          - user_ids (list) di-resolve dari semua nama di responsibility_persons.
          - Junction table kpi_master_users di-sync oleh repository.

        Returns:
            {"status", "count", "message", "group_id", "log_id",
             "data", "unresolved_users"}
        """
        log_id = None
        group_id = None

        try:
            # ── STEP 1: Fetch sheet ──────────────────────────────────
            logger.info("[ingest_kpi_master] Fetching sheet: %s", sheet_url)
            df, spreadsheet_id, sheet_name = self._fetch_sheet(sheet_url)

            # ── STEP 2: Auto-create KPIGroup ─────────────────────────
            logger.info(
                "[ingest_kpi_master] Upserting KPIGroup for sheet_id=%s",
                spreadsheet_id,
            )
            group = await self.group_repo.get_or_create(
                sheet_id=spreadsheet_id,
                group_type="master",
                sheet_url=sheet_url,
                sheet_name=sheet_name,
                nama_grup=sheet_name + " Master " + str(tahun),
                tahun=tahun,
            )
            group_id = group.id
            logger.info("[ingest_kpi_master] KPIGroup ready: group_id=%s", group_id)

            # ── STEP 3: Create IngestionLog (status=running) ─────────
            log = await self.log_repo.create(kpi_group_id=group_id, source_type="master")
            log_id = log.id
            logger.info("[ingest_kpi_master] IngestionLog created: log_id=%s", log_id)

            # ── STEP 4: Parse records ────────────────────────────────
            records, errors = self._parse(df, spreadsheet_id, sheet_name, tahun)
            if not records:
                await self.log_repo.update_status(
                    log_id=log_id,
                    status="failed",
                    total_rows=0,
                    ingested_count=0,
                    errors="Tidak ada records valid setelah parsing.",
                )
                raise ValidationError("Sheet tidak menghasilkan records valid.")

            # Inject group_id ke setiap record
            for record in records:
                record["group_id"] = group_id

            total_rows = len(records)
            logger.info(
                "[ingest_kpi_master] Parsed %s records, %s parse errors",
                total_rows,
                len(errors),
            )

            # ── STEP 5: Resolve user_ids (many-to-many) ───────────────
            records, unresolved_names = await self._inject_user_ids(records)
            if unresolved_names:
                detail = (
                    f"User tidak ditemukan untuk: {', '.join(unresolved_names)}. "
                    "Perbaiki nama di sheet atau tambahkan user terlebih dahulu."
                )
                await self.log_repo.update_status(
                    log_id=log_id,
                    status="failed",
                    total_rows=total_rows,
                    ingested_count=0,
                    errors=detail,
                )
                raise ValidationError(detail)

            # ── STEP 6: Upsert KPI Master + sync junction table ───────
            ingested_count = await self.kpi_repo.upsert_by_group(records)

            # ── STEP 7: Finalize IngestionLog ─────────────────────────
            status = self._resolve_status(ingested_count, total_rows, errors)
            error_summary = self._format_errors(errors) if errors else None

            await self.log_repo.update_status(
                log_id=log_id,
                status=status,
                total_rows=total_rows,
                ingested_count=ingested_count,
                failed_count=total_rows - ingested_count,
                errors=error_summary,
            )

            logger.info(
                "[ingest_kpi_master] Done: %s/%s records, status=%s",
                ingested_count,
                total_rows,
                status,
            )

            # ── STEP 8: Refresh cache statistik kolom NL-to-SQL ───────
            # Statistik hanya berubah saat ada data baru — compute sekali di
            # akhir ingestion, bukan tiap request inference. Kegagalan di sini
            # tidak boleh membatalkan ingestion yang sudah sukses commit.
            await self._refresh_column_statistics()

            return {
                "status":           status,
                "count":            ingested_count,
                "message":          f"Berhasil ingest {ingested_count} dari {total_rows} KPI Master records.",
                "group_id":         str(group_id),
                "log_id":           str(log_id),
                "data":             records,
                "unresolved_users": unresolved_names,
            }

        except (AppError, HTTPException):
            if log_id:
                await self._mark_log_failed(log_id, "Error saat proses ingestion.")
            raise

        except Exception as e:
            logger.error("[ingest_kpi_master] Unexpected error: %s", traceback.format_exc())
            if log_id:
                await self._mark_log_failed(log_id, str(e))
            raise InternalError(f"Error tidak terduga saat ingestion: {str(e)}")

    async def update_and_reingest(
        self,
        group_id:  UUID,
        sheet_url: Optional[str] = None,
        tahun:     Optional[int] = None,
    ) -> dict:
        """
        Update KPIGroup (sheet_url/tahun), hapus seluruh master lama
        (beserta junction rows via CASCADE), lalu ingest ulang.
        """
        log_id = None

        existing_group = await self.group_repo.get_by_id(group_id)
        if existing_group is None:
            raise NotFoundError(f"KPI {group_id} tidak ditemukan.")

        try:
            effective_sheet_url = sheet_url if sheet_url is not None else existing_group.sheet_url
            effective_tahun = tahun if tahun is not None else existing_group.tahun
            if effective_tahun is None:
                raise BadRequestError("Tahun wajib diisi untuk KPI Master.")

            logger.info(
                "[update_and_reingest] Fetching sheet for group_id=%s: %s",
                group_id,
                effective_sheet_url,
            )
            df, spreadsheet_id, sheet_name = self._fetch_sheet(effective_sheet_url or "")

            await self.group_repo.update(
                group_id=group_id,
                fields={
                    "sheet_url":  effective_sheet_url,
                    "sheet_id":   spreadsheet_id,
                    "sheet_name": sheet_name,
                    "nama_grup":  f"{sheet_name} Master {effective_tahun}",
                    "tahun":      effective_tahun,
                },
            )

            # Hapus master lama — junction rows terhapus via ON DELETE CASCADE
            deleted_count = await self.kpi_repo.delete_by_group_id(group_id)
            logger.info(
                "[update_and_reingest] Deleted %s old records for group_id=%s",
                deleted_count,
                group_id,
            )

            log = await self.log_repo.create(kpi_group_id=group_id, source_type="master")
            log_id = log.id

            records, errors = self._parse(df, spreadsheet_id, sheet_name, effective_tahun)
            if not records:
                await self.log_repo.update_status(
                    log_id=log_id,
                    status="failed",
                    total_rows=0,
                    ingested_count=0,
                    errors="Tidak ada records valid setelah parsing.",
                )
                raise ValidationError("Sheet tidak menghasilkan records valid.")

            for record in records:
                record["group_id"] = group_id

            # Resolve user_ids — lenient: nama tak dikenal dicatat di errors
            records, unresolved_names = await self._inject_user_ids(records)
            if unresolved_names:
                errors.extend(
                    f"[user_lookup] '{name}' tidak ditemukan di users — user_ids tidak ter-assign"
                    for name in unresolved_names
                )

            total_rows = len(records)
            ingested_count = await self.kpi_repo.upsert_by_group(records)

            status = self._resolve_status(ingested_count, total_rows, errors)
            error_summary = self._format_errors(errors) if errors else None

            await self.log_repo.update_status(
                log_id=log_id,
                status=status,
                total_rows=total_rows,
                ingested_count=ingested_count,
                failed_count=total_rows - ingested_count,
                errors=error_summary,
            )

            return {
                "status":           status,
                "count":            ingested_count,
                "group_id":         str(group_id),
                "log_id":           str(log_id),
                "unresolved_users": unresolved_names,
            }

        except (AppError, HTTPException):
            if log_id:
                await self._mark_log_failed(log_id, "Error saat update_and_reingest.")
            raise

        except Exception as e:
            logger.error(
                "[update_and_reingest] Unexpected error: %s", traceback.format_exc()
            )
            if log_id:
                await self._mark_log_failed(log_id, str(e))
            raise InternalError(
                f"Error tidak terduga saat update_and_reingest: {str(e)}"
            )

    # ================================================================ #
    #  PRIVATE: User ID resolution                                      #
    # ================================================================ #

    async def _inject_user_ids(
        self,
        records: list[dict],
    ) -> tuple[list[dict], list[str]]:
        """
        Resolve responsibility_persons (comma-separated names) → user_ids (list[UUID]).

        Tiap record:
          - Key "responsibility_persons" di-pop.
          - Key "user_ids" (list[UUID]) di-inject — kosong jika tidak ada PIC valid.

        Mengembalikan:
          records        — list record yang sudah di-inject user_ids.
          unresolved_all — semua nama (de-duplikasi global) yang gagal di-resolve.
        """
        lookup = UserLookupUtil(self.db)
        await lookup.preload()

        unresolved_all: list[str] = []
        seen_unresolved: set[str] = set()

        for record in records:
            raw_persons: str | None = record.pop("responsibility_persons", None)
            resolved, unresolved = await lookup.all_ids_in_text(raw_persons)
            record["user_ids"] = resolved

            for name in unresolved:
                if name not in seen_unresolved:
                    unresolved_all.append(name)
                    seen_unresolved.add(name)

        return records, unresolved_all

    # ================================================================ #
    #  PRIVATE: Sheet & parse helpers                                   #
    # ================================================================ #

    def _fetch_sheet(self, sheet_url: str):
        try:
            from service.googleSheetService import GoogleSheetService
            svc = GoogleSheetService()
            df, spreadsheet_id, sheet_name, _ = svc.fetch_sheet_as_dataframe(
                sheet_url=sheet_url,
                sheet_name="KPI",
                sheet_index=0,
                header=None,
            )
            return df, spreadsheet_id, sheet_name
        except HTTPException:
            raise
        except Exception as e:
            raise InternalError(f"Error fetching sheet: {str(e)}")

    def _parse(self, df, spreadsheet_id: str, sheet_name: str, tahun: int):
        try:
            from utils.helper.parser.kpiMasterParser import parse_kpi_master_dataframe
            return parse_kpi_master_dataframe(df, spreadsheet_id, sheet_name, tahun=tahun)
        except ValueError as e:
            raise ValidationError(str(e))

    # ================================================================ #
    #  PRIVATE: Log helpers                                             #
    # ================================================================ #

    def _resolve_status(self, ingested_count: int, total_rows: int, errors: list) -> str:
        """Status biner: success atau failed."""
        if ingested_count == 0 or ingested_count < total_rows or errors:
            return "failed"
        return "success"

    def _format_errors(self, errors: list) -> str:
        if not errors:
            return ""
        MAX_ERRORS = 20
        result = "; ".join(str(e) for e in errors[:MAX_ERRORS])
        if len(errors) > MAX_ERRORS:
            result += f" ... dan {len(errors) - MAX_ERRORS} error lainnya."
        return result

    async def _mark_log_failed(self, log_id: UUID, reason: str) -> None:
        """Best-effort update log ke 'failed'. Tidak raise jika gagal."""
        try:
            await self.log_repo.update_status(
                log_id=log_id,
                status="failed",
                errors=reason,
            )
        except Exception:
            logger.warning("[ingest_kpi_master] Gagal update log %s ke 'failed'", log_id)

    async def _refresh_column_statistics(self) -> None:
        """Best-effort refresh cache statistik NL-to-SQL. Tidak raise jika gagal."""
        try:
            await ColumnStatisticsService(self.db).refresh_statistics()
            logger.info("[ingest_kpi_master] Cache statistik NL-to-SQL di-refresh")
        except Exception:
            logger.warning(
                "[ingest_kpi_master] Gagal refresh cache statistik NL-to-SQL",
                exc_info=True,
            )