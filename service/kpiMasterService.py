"""
service/kpiMasterService.py
Business logic untuk KPI Master management.
Layer ini berfungsi sebagai orchestrator antara controller dan repository,
menangani validasi, transformasi data, dan logika bisnis.
"""

from typing import Optional, Dict, Any
from uuid import UUID
import logging

from fastapi import HTTPException

from repository.kpiMasterRepository import KPIMasterRepository
from model.KPIMaster import KPIMasterORM

logger = logging.getLogger(__name__)


class KPIMasterService:
    """
    Service untuk manage KPI Master records.
    Menangani business logic, validasi, dan orchestration.
    """

    def __init__(self, repository: KPIMasterRepository):
        """
        Initialize service dengan dependency injection repository.

        Args:
            repository: KPIMasterRepository instance
        """
        self.repo = repository

    # ================================================================ #
    #  UPSERT Operations (Create/Update)                               #
    # ================================================================ #

    async def upsert_records(self, records: list[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Upsert KPI Master records. Conflict on (tahun, kpi_name) → update.
        Records baru akan dibuat, records existing akan diupdate.

        Args:
            records: List[Dict] dengan KPI Master data

        Returns:
            Dict dengan hasil: count, status, message

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
                self._validate_required_fields(
                    record, ["tahun", "kpi_name", "category"])
                self._validate_tahun(record["tahun"])
            except HTTPException as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Record {idx}: {e.detail}"
                )

        logger.info(f"Upserting {len(records)} KPI Master records")

        try:
            count = await self.repo.upsert_by_tahun(records)
            return {
                "status": "success",
                "count": count,
                "message": f"Berhasil upsert {count} KPI Master records"
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error upserting KPI Master records: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal upsert KPI Master records: {str(e)}"
            )

    # ================================================================ #
    #  GROUP/AGGREGATE Operations (Grouped by Source Sheet Name)        #
    # ================================================================ #

    async def get_grouped_records(self, skip: int = 0, limit: int = 100) -> Dict[str, Any]:
        """
        Ambil KPI Masters yang dikelompokkan berdasarkan source_sheet_name (nama file).
        Setiap group menampilkan: source_sheet_name, total_count, tahun_list, categories, kpi_count, last_updated.

        Args:
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Dict dengan: groups, pagination info
        """
        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        logger.info(f"Fetching grouped KPI Masters")

        try:
            groups = await self.repo.get_grouped_by_source_sheet_name(skip=skip, limit=limit + 1)

            has_more = len(groups) > limit
            groups = groups[:limit]

            return {
                "groups": groups,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": len(groups),
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching grouped KPI Masters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters: {str(e)}"
            )

    async def get_grouped_records_with_filters(self,
                                               tahun: Optional[int] = None,
                                               category: Optional[str] = None,
                                               skip: int = 0,
                                               limit: int = 100) -> Dict[str, Any]:
        """
        Ambil KPI Masters grouped by source_sheet_name dengan optional filters.

        Args:
            tahun: Filter by tahun
            category: Filter by category
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Dict dengan: filtered groups, pagination info
        """
        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        if tahun:
            self._validate_tahun(tahun)

        logger.info(
            f"Fetching grouped KPI Masters with filters - tahun: {tahun}, category: {category}")

        try:
            groups = await self.repo.get_grouped_by_source_sheet_name_with_filters(
                tahun=tahun,
                category=category,
                skip=skip,
                limit=limit + 1
            )

            has_more = len(groups) > limit
            groups = groups[:limit]

            return {
                "groups": groups,
                "pagination": {
                    "skip": skip,
                    "limit": limit,
                    "total": len(groups),
                    "has_more": has_more
                }
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                f"Error fetching grouped KPI Masters with filters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters dengan filters: {str(e)}"
            )

    async def get_detail_records_by_source_sheet_name(self,
                                                      source_sheet_name: str,
                                                      skip: int = 0,
                                                      limit: int = 100) -> Dict[str, Any]:
        """
        Ambil detail masters untuk satu source_sheet_name tertentu (expand group).
        Menampilkan semua individual masters dalam satu file group.

        Args:
            source_sheet_name: Nama file yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            Dict dengan: source_sheet_name, masters, pagination info
        """
        if not source_sheet_name or not source_sheet_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Source sheet name tidak boleh kosong"
            )

        # Validasi pagination
        skip = max(0, skip)
        limit = min(limit, 500)  # Max limit 500

        logger.info(f"Fetching detail masters for sheet: {source_sheet_name}")

        try:
            records = await self.repo.get_detail_masters_by_source_sheet_name(
                source_sheet_name=source_sheet_name,
                skip=skip,
                limit=limit + 1
            )

            has_more = len(records) > limit
            records = records[:limit]

            return {
                "source_sheet_name": source_sheet_name,
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
            logger.error(f"Error fetching detail masters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail masters: {str(e)}"
            )

    async def delete_by_source_sheet_name(self, source_sheet_name: str) -> Dict[str, Any]:
        """
        Hapus semua KPI Master yang memiliki source_sheet_name tertentu.

        Args:
            source_sheet_name: Nama file yang ingin dihapus

        Returns:
            Dict dengan: deleted_count, message
        """
        if not source_sheet_name or not source_sheet_name.strip():
            raise HTTPException(
                status_code=400,
                detail="Source sheet name tidak boleh kosong"
            )

        logger.info(f"Deleting KPI Masters for sheet: {source_sheet_name}")

        try:
            deleted_count = await self.repo.delete_by_source_sheet_name(source_sheet_name)
            return {
                "deleted_count": deleted_count,
                "message": f"Berhasil hapus {deleted_count} records untuk sheet '{source_sheet_name}'"
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting KPI Masters: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Masters: {str(e)}"
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

    def _validate_kpi_master_fields(self, record_data: Dict[str, Any]) -> None:
        """
        Validasi fields spesifik untuk KPI Master.

        Args:
            record_data: Record data

        Raises:
            HTTPException: Jika ada field yang invalid
        """
        # Validasi category
        valid_categories = [
            "Strategic", "Operational", "Financial", "Customer", "Internal Process"
        ]  # Bisa disesuaikan dengan data actual

        if "category" in record_data:
            category = record_data.get("category")
            if category and not any(cat.lower() in category.lower() for cat in valid_categories):
                logger.warning(f"Unknown category: {category}")
