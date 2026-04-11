"""
service/kpiTrackerService.py
Business logic untuk KPI Tracker management.
Layer ini berfungsi sebagai orchestrator antara controller dan repository,
menangani validasi, transformasi data, dan logika bisnis.
"""

from typing import Optional, Dict, Any
from uuid import UUID
import logging

from fastapi import HTTPException

from repository.kpiTrackerRepository import kpiTrackerRepository
from model.KPITracker import KPIRecordORM

logger = logging.getLogger(__name__)


class KPITrackerService:
    """
    Service untuk manage KPI Tracker records.
    Menangani business logic, validasi, dan orchestration.
    """

    def __init__(self, repository: kpiTrackerRepository):
        """
        Initialize service dengan dependency injection repository.

        Args:
            repository: kpiTrackerRepository instance
        """
        self.repo = repository

    # ================================================================ #
    #  CREATE Operations                                               #
    # ================================================================ #

    async def bulk_create_records(self, records: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Buat multiple KPI records sekaligus (bulk insert).

        Args:
            records: List[Dict] dengan record data

        Returns:
            Dict dengan hasil: count, status, failed_records (jika ada)

        Raises:
            HTTPException: Jika data invalid atau error database
        """
        if not records:
            raise HTTPException(
                status_code=400,
                detail="Records list tidak boleh kosong"
            )

        if len(records) > 10000:
            raise HTTPException(
                status_code=400,
                detail="Maksimal 10000 records per request"
            )

        # Validasi semua records
        for idx, record in enumerate(records):
            try:
                self._validate_required_fields(record, ["nama_kpi"])
                if "tahun" in record and record["tahun"]:
                    self._validate_tahun(record["tahun"])
            except HTTPException as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Record {idx}: {e.detail}"
                )

        logger.info(f"Bulk creating {len(records)} KPI records")

        try:
            count = await self.repo.bulk_insert_kpi_records(records)
            return {
                "status": "success",
                "count": count,
                "message": f"Berhasil membuat {count} KPI records"
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error bulk creating KPI records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal bulk create KPI records: {str(e)}"
            )

    # ================================================================ #
    #  READ Operations                                                 #
    # ================================================================ #

    async def get_record_by_id(self, record_id: UUID) -> KPIRecordORM:
        """
        Ambil satu KPI record by ID.

        Args:
            record_id: UUID dari record

        Returns:
            KPIRecordORM: Record yang ditemukan

        Raises:
            HTTPException: 404 jika record tidak ditemukan
        """
        logger.debug(f"Fetching KPI record: {record_id}")

        record = await self.repo.get_kpi_record_by_id(record_id)
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"KPI record dengan ID {record_id} tidak ditemukan"
            )

        return record

    async def get_all_records(self,
                              nama_kpi: Optional[str] = None,
                              tahun: Optional[int] = None,
                              nama_orang: Optional[str] = None,
                              skip: int = 0,
                              limit: int = 100) -> Dict[str, Any]:
        """
        Ambil semua KPI records dengan optional filters dan pagination.

        Args:
            nama_kpi: Filter by nama KPI
            tahun: Filter by tahun
            nama_orang: Filter by nama orang
            skip: Pagination offset
            limit: Pagination limit (max 500)

        Returns:
            Dict dengan: records, total, skip, limit, has_more

        Raises:
            HTTPException: Jika parameter invalid
        """
        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching KPI records with filters - tahun: {tahun}, nama_kpi: {nama_kpi}")

        try:
            records = await self.repo.get_all_kpi_records(
                nama_kpi=nama_kpi,
                tahun=tahun,
                nama_orang=nama_orang,
                skip=skip,
                limit=limit + 1  # +1 untuk detect has_more
            )

            has_more = len(records) > limit
            records = records[:limit]

            total = await self.repo.count_kpi_records()

            return {
                "records": records,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": total,
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching KPI records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil KPI records: {str(e)}"
            )

    async def get_records_by_tahun(self, tahun: int, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        Ambil KPI records untuk tahun tertentu.

        Args:
            tahun: Tahun yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Dict dengan: records, pagination info
        """
        self._validate_tahun(tahun)

        return await self.get_all_records(tahun=tahun, skip=skip, limit=limit)

    async def get_records_count(self) -> Dict[str, int]:
        """
        Ambil total count KPI records.

        Returns:
            Dict dengan: total
        """
        try:
            total = await self.repo.count_kpi_records()
            return {"total": total}
        except Exception as e:
            logger.error(f"Error counting KPI records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hitung KPI records: {str(e)}"
            )

    async def get_grouped_records(self, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        Ambil KPI records yang dikelompokkan berdasarkan nama_kpi.
        Setiap group menampilkan: nama_kpi, total_count, tahun_list, sheet_names, sheet_count, last_updated.

        Args:
            skip: Pagination offset
            limit: Pagination limit (max 500)

        Returns:
            Dict dengan: groups, pagination info
        """
        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        logger.info(f"Fetching grouped KPI records")

        try:
            groups = await self.repo.get_grouped_by_nama_kpi(skip=skip, limit=limit + 1)

            has_more = len(groups) > limit
            groups = groups[:limit]

            total = await self.repo.count_kpi_records()

            return {
                "groups": groups,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": total,
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching grouped KPI records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}"
            )

    async def get_grouped_records_with_filters(self,
                                               tahun: Optional[int] = None,
                                               nama_orang: Optional[str] = None,
                                               skip: int = 0,
                                               limit: int = 100) -> Dict[str, Any]:
        """
        Ambil KPI records grouped by nama_kpi dengan optional filters.

        Args:
            tahun: Filter by tahun
            nama_orang: Filter by nama orang
            skip: Pagination offset
            limit: Pagination limit (max 500)

        Returns:
            Dict dengan: groups, pagination info
        """
        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching grouped KPI records with filters - tahun: {tahun}, nama_orang: {nama_orang}")

        try:
            groups = await self.repo.get_grouped_by_nama_kpi_with_filters(
                tahun=tahun,
                nama_orang=nama_orang,
                skip=skip,
                limit=limit + 1
            )

            has_more = len(groups) > limit
            groups = groups[:limit]

            total = await self.repo.count_kpi_records()

            return {
                "groups": groups,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": total,
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching grouped KPI records with filters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI records: {str(e)}"
            )

    async def get_detail_records_by_nama_kpi(self, nama_kpi: str, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        Ambil detail records untuk satu nama_kpi tertentu.
        Digunakan untuk melihat semua individual records dalam satu group.

        Args:
            nama_kpi: Nama KPI yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Dict dengan: records, pagination info, nama_kpi
        """
        if not nama_kpi or not nama_kpi.strip():
            raise HTTPException(
                status_code=400,
                detail="Nama KPI tidak boleh kosong"
            )

        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)

        logger.info(f"Fetching detail records for nama_kpi: {nama_kpi}")

        try:
            records = await self.repo.get_detail_records_by_nama_kpi(
                nama_kpi=nama_kpi,
                skip=skip,
                limit=limit + 1
            )

            has_more = len(records) > limit
            records = records[:limit]

            return {
                "nama_kpi": nama_kpi,
                "records": records,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": len(records),
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching detail records by nama_kpi: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail records: {str(e)}"
            )

    # ================================================================ #
    #  UPDATE Operations                                               #
    # ================================================================ #

    async def update_record(self, record_id: UUID, update_data: Dict[str, Any]) -> KPIRecordORM:
        """
        Update KPI record.

        Args:
            record_id: UUID dari record yang diupdate
            update_data: Dict dengan field yang diupdate

        Returns:
            KPIRecordORM: Record yang sudah diupdate

        Raises:
            HTTPException: 404 jika record tidak ditemukan atau error update
        """
        if not update_data:
            raise HTTPException(
                status_code=400,
                detail="Update data tidak boleh kosong"
            )

        # Validasi tahun jika diupdate
        if "tahun" in update_data and update_data["tahun"]:
            self._validate_tahun(update_data["tahun"])

        logger.info(f"Updating KPI record: {record_id}")

        try:
            return await self.repo.update_kpi_record(record_id, update_data)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating KPI record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal update KPI record: {str(e)}"
            )

    # ================================================================ #
    #  DELETE Operations                                               #
    # ================================================================ #

    async def delete_record(self, record_id: UUID) -> Dict[str, str]:
        """
        Hapus satu KPI record.

        Args:
            record_id: UUID dari record yang dihapus

        Returns:
            Dict dengan: message

        Raises:
            HTTPException: 404 jika record tidak ditemukan
        """
        logger.info(f"Deleting KPI record: {record_id}")

        try:
            result = await self.repo.delete_kpi_record(record_id)
            if result:
                return {"message": f"KPI record {record_id} berhasil dihapus"}
            raise HTTPException(
                status_code=404,
                detail="Record tidak ditemukan"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting KPI record: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI record: {str(e)}"
            )

    async def delete_records_by_ids(self, record_ids: list[UUID]) -> Dict[str, Any]:
        """
        Hapus multiple KPI records.

        Args:
            record_ids: List[UUID] dari records yang dihapus

        Returns:
            Dict dengan: count, message

        Raises:
            HTTPException: Jika list kosong atau error delete
        """
        if not record_ids:
            raise HTTPException(
                status_code=400,
                detail="Record IDs list tidak boleh kosong"
            )

        if len(record_ids) > 1000:
            raise HTTPException(
                status_code=400,
                detail="Maksimal 1000 records per request"
            )

        logger.info(f"Deleting {len(record_ids)} KPI records")

        try:
            count = await self.repo.delete_kpi_records_by_ids(record_ids)
            return {
                "status": "success",
                "count": count,
                "message": f"Berhasil menghapus {count} KPI records"
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error bulk deleting KPI records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI records: {str(e)}"
            )

    # ================================================================ #
    #  HELPER Methods (Private)                                        #
    # ================================================================ #

    def _validate_required_fields(self, data: Dict[str, Any], required: list[str]) -> None:
        """
        Validasi required fields ada dan tidak kosong.

        Args:
            data: Data dict
            required: List field yang required

        Raises:
            HTTPException: Jika field ada yang kosong atau tidak ada
        """
        for field in required:
            if field not in data or not data[field]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Field '{field}' adalah required dan tidak boleh kosong"
                )

    def _validate_tahun(self, tahun: int) -> None:
        """
        Validasi nilai tahun.

        Args:
            tahun: Nilai tahun

        Raises:
            HTTPException: Jika tahun invalid
        """
        if not isinstance(tahun, int):
            raise HTTPException(
                status_code=400,
                detail="Tahun harus berupa integer"
            )

        current_year = 2026  # Bisa diganti dengan datetime.now().year
        if tahun < 2000 or tahun > current_year + 5:
            raise HTTPException(
                status_code=400,
                detail=f"Tahun harus antara 2000 dan {current_year + 5}"
            )

    async def _normalize_record_data(self, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize dan clean record data sebelum disimpan.

        Args:
            record_data: Raw record data

        Returns:
            Dict dengan data yang sudah dinormalisasi
        """
        normalized = record_data.copy()

        # Trim string fields
        for key, value in normalized.items():
            if isinstance(value, str):
                normalized[key] = value.strip()

        return normalized
