"""
service/kpiMasterService.py
Business logic untuk KPI Master management.

Perubahan dari versi sebelumnya:
  - upsert_records: validasi sekarang menggunakan (group_id, kpi_name)
    bukan (tahun, kpi_name). group_id WAJIB ada di setiap record.
  - _validate_required_fields: tambah 'group_id' ke required fields.
  - Grouped operations: dikembalikan apa adanya dari repository
    (repository sudah handle JOIN ke kpi_groups).

Interface publik (method signatures & return shapes) TIDAK BERUBAH
agar controller tidak perlu dimodifikasi.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import HTTPException

from model.KPIMaster import KPIMasterORM
from repository.kpiMasterRepository import KPIMasterRepository

logger = logging.getLogger(__name__)


class KPIMasterService:

    def __init__(self, repository: KPIMasterRepository):
        self.repo: KPIMasterRepository = repository

    # ================================================================ #
    #  UPSERT                                                           #
    # ================================================================ #

    async def upsert_records(self, records: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Upsert KPI Master records.

        Records HARUS menyertakan 'group_id' (UUID string atau UUID object).
        Conflict key: (group_id, kpi_name) → update field konten KPI.

        Args:
            records: List[Dict] KPI Master data, tiap record sudah berisi group_id.

        Returns:
            {"status", "count", "message"}
        """
        if not records:
            raise HTTPException(
                status_code=400, detail="Records list tidak boleh kosong")

        if len(records) > 10_000:
            raise HTTPException(
                status_code=400, detail="Maksimal 10000 records per request")

        for idx, record in enumerate(records):
            try:
                # group_id wajib — diisi oleh ingestion service setelah KPIGroup dibuat
                self._validate_required_fields(
                    record, ["group_id", "tahun", "kpi_name", "category"]
                )
                self._validate_tahun(record["tahun"])
            except HTTPException as e:
                raise HTTPException(
                    status_code=400, detail=f"Record {idx}: {e.detail}")

        logger.info(f"Upserting {len(records)} KPI Master records")

        try:
            count = await self.repo.upsert_by_group(records)
            return {
                "status":  "success",
                "count":   count,
                "message": f"Berhasil upsert {count} KPI Master records",
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error upserting KPI Master records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal upsert KPI Master records: {str(e)}",
            )

    # ================================================================ #
    #  GROUP/AGGREGATE                                                  #
    # ================================================================ #

    async def get_grouped_records(
        self, skip: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """
        Ambil KPI Masters dikelompokkan per sheet.
        Repository sudah handle JOIN ke kpi_groups — service hanya wrap pagination.
        """
        skip = max(0, skip)
        limit = min(limit, 500)

        logger.info("Fetching grouped KPI Masters")

        try:
            groups = await self.repo.get_grouped_by_source_sheet_name(
                skip=skip, limit=limit + 1
            )
            has_more = len(groups) > limit
            groups = groups[:limit]

            return {
                "groups": groups,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    len(groups),
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching grouped KPI Masters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters: {str(e)}",
            )

    async def get_grouped_records_with_filters(
        self,
        tahun:    Optional[int] = None,
        category: Optional[str] = None,
        skip:     int = 0,
        limit:    int = 100,
    ) -> Dict[str, Any]:
        skip = max(0, skip)
        limit = min(limit, 500)

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching grouped KPI Masters — tahun={tahun}, category={category}"
        )

        try:
            groups = await self.repo.get_grouped_by_source_sheet_name_with_filters(
                tahun=tahun,
                category=category,
                skip=skip,
                limit=limit + 1,
            )
            has_more = len(groups) > limit
            groups = groups[:limit]

            return {
                "groups": groups,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    len(groups),
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching grouped KPI Masters with filters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters dengan filters: {str(e)}",
            )

    async def get_detail_records_by_source_sheet_name(
        self,
        source_sheet_name: str,
        skip:  int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        if not source_sheet_name or not source_sheet_name.strip():
            raise HTTPException(
                status_code=400, detail="Source sheet name tidak boleh kosong"
            )

        skip = max(0, skip)
        limit = min(limit, 500)

        logger.info(f"Fetching detail masters for sheet: {source_sheet_name}")

        try:
            records = await self.repo.get_detail_masters_by_source_sheet_name(
                source_sheet_name=source_sheet_name,
                skip=skip,
                limit=limit + 1,
            )
            has_more = len(records) > limit
            records = records[:limit]

            return {
                "source_sheet_name": source_sheet_name,
                "records":           records,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    len(records),
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching detail masters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail masters: {str(e)}",
            )

    # ================================================================ #
    #  PRIVATE Helpers                                                 #
    # ================================================================ #

    def _validate_required_fields(
        self, data: Dict[str, Any], required: list[str]
    ) -> None:
        for field in required:
            if field not in data or not data[field]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field}' adalah required dan tidak boleh kosong",
                )

    def _validate_tahun(self, tahun: int) -> None:
        if not isinstance(tahun, int):
            raise HTTPException(
                status_code=400, detail="Tahun harus berupa integer")

        current_year = 2026
        if tahun < 2000 or tahun > current_year + 5:
            raise HTTPException(
                status_code=400,
                detail=f"Tahun harus antara 2000 dan {current_year + 5}",
            )
