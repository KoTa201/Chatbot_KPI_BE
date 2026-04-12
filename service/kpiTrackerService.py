"""
service/kpiTrackerService.py
Business logic untuk KPI Tracker management.

Perubahan dari versi sebelumnya:
  - bulk_create_records: field required berubah dari 'nama_kpi' → 'group_id'.
    kpi_master_id tidak divalidasi di sini (boleh null = unmatched).
  - get_all_records: parameter nama_kpi dan tahun tetap ada — diteruskan ke
    repository yang handle JOIN ke kpi_master secara transparan.
  - _validate_required_fields: tidak ada perubahan struktural.
  - update_record: field 'tahun' dihapus dari validasi — tidak ada di model baru.

Interface publik (semua method signatures dan return shapes) TIDAK BERUBAH
agar controller tidak perlu dimodifikasi.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import HTTPException

from model.KPITracker import KPITrackerORM
from repository.kpiTrackerRepository import KPITrackerRepository

logger = logging.getLogger(__name__)


class KPITrackerService:

    def __init__(self, repository: KPITrackerRepository):
        self.repo = repository

    # ================================================================ #
    #  CREATE                                                           #
    # ================================================================ #

    async def bulk_create_records(self, records: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Bulk insert KPI Tracker records.

        Records HARUS sudah berisi 'group_id'. kpi_master_id boleh None
        (tracker yang belum bisa di-match ke master tetap disimpan).

        Args:
            records: List[Dict] — tiap record sudah berisi group_id dan
                     (opsional) kpi_master_id dari ingestion service.

        Returns:
            {"status", "count", "message"}
        """
        if not records:
            raise HTTPException(
                status_code=400, detail="Records list tidak boleh kosong"
            )
        if len(records) > 10_000:
            raise HTTPException(
                status_code=400, detail="Maksimal 10000 records per request"
            )

        for idx, record in enumerate(records):
            try:
                # group_id wajib — diisi oleh ingestion service
                self._validate_required_fields(record, ["group_id"])
            except HTTPException as e:
                raise HTTPException(
                    status_code=400, detail=f"Record {idx}: {e.detail}"
                )

        logger.info(f"Bulk creating {len(records)} KPI Tracker records")

        try:
            count = await self.repo.bulk_insert_kpi_records(records)
            return {
                "status":  "success",
                "count":   count,
                "message": f"Berhasil membuat {count} KPI Tracker records",
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error bulk creating KPI Tracker records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal bulk create KPI Tracker records: {str(e)}",
            )

    # ================================================================ #
    #  READ                                                             #
    # ================================================================ #

    async def get_record_by_id(self, record_id: UUID) -> KPITrackerORM:
        record = await self.repo.get_kpi_record_by_id(record_id)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"KPI record dengan ID {record_id} tidak ditemukan",
            )
        return record

    async def get_all_records(
        self,
        nama_kpi:   Optional[str] = None,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> Dict[str, Any]:
        """
        Ambil semua KPI Tracker records.

        nama_kpi dan tahun diteruskan ke repository yang menangani JOIN
        ke kpi_master_records secara internal. Interface tidak berubah.
        """
        skip = max(0, skip)
        limit = min(limit, 500)

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching KPI Tracker records — tahun={tahun}, nama_kpi={nama_kpi}"
        )

        try:
            records = await self.repo.get_all_kpi_records(
                nama_kpi=nama_kpi,
                tahun=tahun,
                nama_orang=nama_orang,
                skip=skip,
                limit=limit + 1,
            )
            has_more = len(records) > limit
            records = records[:limit]
            total = await self.repo.count_kpi_records()

            return {
                "records": records,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    total,
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching KPI Tracker records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI records: {str(e)}",
            )

    async def get_records_by_tahun(
        self, tahun: int, skip: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        self._validate_tahun(tahun)
        return await self.get_all_records(tahun=tahun, skip=skip, limit=limit)

    async def get_records_count(self) -> Dict[str, int]:
        try:
            total = await self.repo.count_kpi_records()
            return {"total": total}
        except Exception as e:
            logger.error(f"Error counting KPI Tracker records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hitung KPI records: {str(e)}",
            )

    async def get_grouped_records(
        self, skip: int = 0, limit: int = 100
    ) -> Dict[str, Any]:
        """
        KPI Tracker dikelompokkan per nama KPI (via kpi_master).
        Response shape sama seperti sebelumnya — controller tidak perlu tahu
        bahwa nama KPI sekarang diambil lewat JOIN.
        """
        skip = max(0, skip)
        limit = min(limit, 500)

        logger.info("Fetching grouped KPI Tracker records")

        try:
            groups = await self.repo.get_grouped_by_nama_kpi(
                skip=skip, limit=limit + 1
            )
            has_more = len(groups) > limit
            groups = groups[:limit]
            total = await self.repo.count_kpi_records()

            return {
                "groups": groups,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    total,
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching grouped KPI Tracker records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}",
            )

    async def get_grouped_records_with_filters(
        self,
        tahun:      Optional[int] = None,
        nama_orang: Optional[str] = None,
        skip:       int = 0,
        limit:      int = 100,
    ) -> Dict[str, Any]:
        skip = max(0, skip)
        limit = min(limit, 500)

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching grouped KPI Tracker records — tahun={tahun}, nama_orang={nama_orang}"
        )

        try:
            groups = await self.repo.get_grouped_by_nama_kpi_with_filters(
                tahun=tahun,
                nama_orang=nama_orang,
                skip=skip,
                limit=limit + 1,
            )
            has_more = len(groups) > limit
            groups = groups[:limit]
            total = await self.repo.count_kpi_records()

            return {
                "groups": groups,
                "pagination": {
                    "skip":     skip,
                    "limit":    limit,
                    "total":    total,
                    "has_more": has_more,
                },
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching grouped KPI Tracker records with filters: {str(e)}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}",
            )

    async def get_detail_records_by_nama_kpi(
        self,
        nama_kpi: str,
        skip:     int = 0,
        limit:    int = 100,
    ) -> Dict[str, Any]:
        if not nama_kpi or not nama_kpi.strip():
            raise HTTPException(
                status_code=400, detail="Nama KPI tidak boleh kosong"
            )

        skip = max(0, skip)
        limit = min(limit, 500)

        logger.info(f"Fetching detail KPI Tracker records for: {nama_kpi}")

        try:
            records = await self.repo.get_detail_records_by_nama_kpi(
                nama_kpi=nama_kpi,
                skip=skip,
                limit=limit + 1,
            )
            has_more = len(records) > limit
            records = records[:limit]

            return {
                "nama_kpi":  nama_kpi,
                "records":   records,
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
            logger.error(
                f"Error fetching detail KPI Tracker records by nama_kpi: {str(e)}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail records: {str(e)}",
            )

    # ================================================================ #
    #  UPDATE / DELETE                                                  #
    # ================================================================ #

    async def update_record(
        self, record_id: UUID, update_data: Dict[str, Any]
    ) -> KPITrackerORM:
        if not update_data:
            raise HTTPException(
                status_code=400, detail="Update data tidak boleh kosong"
            )

        logger.info(f"Updating KPI Tracker record: {record_id}")
        try:
            return await self.repo.update_kpi_record(record_id, update_data)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating KPI Tracker record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI record: {str(e)}",
            )

    async def delete_record(self, record_id: UUID) -> Dict[str, str]:
        logger.info(f"Deleting KPI Tracker record: {record_id}")
        try:
            result = await self.repo.delete_kpi_record(record_id)
            if result:
                return {"message": f"KPI record {record_id} berhasil dihapus"}
            raise HTTPException(
                status_code=404, detail="Record tidak ditemukan")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting KPI Tracker record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI record: {str(e)}",
            )

    async def delete_records_by_ids(
        self, record_ids: list[UUID]
    ) -> Dict[str, Any]:
        if not record_ids:
            raise HTTPException(
                status_code=400, detail="Record IDs list tidak boleh kosong"
            )
        if len(record_ids) > 1000:
            raise HTTPException(
                status_code=400, detail="Maksimal 1000 records per request"
            )

        logger.info(f"Deleting {len(record_ids)} KPI Tracker records")
        try:
            count = await self.repo.delete_kpi_records_by_ids(record_ids)
            return {
                "status":  "success",
                "count":   count,
                "message": f"Berhasil menghapus {count} KPI records",
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error bulk deleting KPI Tracker records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI records: {str(e)}",
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
                status_code=400, detail="Tahun harus berupa integer"
            )
        current_year = 2026
        if tahun < 2000 or tahun > current_year + 5:
            raise HTTPException(
                status_code=400,
                detail=f"Tahun harus antara 2000 dan {current_year + 5}",
            )
