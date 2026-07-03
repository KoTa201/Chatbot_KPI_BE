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

from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AppError, BadRequestError, InternalError
from model.KPIMaster import KPIMaster
from repository.kpiMasterRepository import KPIMasterRepository

logger = logging.getLogger(__name__)


class KPIMasterService:

    def __init__(
        self,
        db: AsyncSession | None = None,
        repository: KPIMasterRepository | None = None,
    ):
        if repository is not None:
            self.repo: KPIMasterRepository = repository
        elif isinstance(db, KPIMasterRepository):
            self.repo: KPIMasterRepository = db
        elif db is not None:
            self.repo: KPIMasterRepository = KPIMasterRepository(db)
        else:
            raise ValueError("KPIMasterService requires db or repository")

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
            raise BadRequestError("Records list tidak boleh kosong")

        if len(records) > 10_000:
            raise BadRequestError("Maksimal 10000 records per request")

        for idx, record in enumerate(records):
            try:
                # group_id wajib — diisi oleh ingestion service setelah KPIGroup dibuat
                self._validate_required_fields(
                    record, ["group_id", "tahun", "kpi_name", "category"]
                )
                self._validate_tahun(record["tahun"])
            except BadRequestError as e:
                raise BadRequestError(f"Record {idx}: {e.message}")

        logger.info(f"Upserting {len(records)} KPI Master records")

        try:
            count = await self.repo.upsert_by_group(records)
            return {
                "status":  "success",
                "count":   count,
                "message": f"Berhasil upsert {count} KPI Master records",
            }
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error upserting KPI Master records: {str(e)}")
            raise InternalError(f"Gagal upsert KPI Master records: {str(e)}")

    # ================================================================ #
    #  PRIVATE Helpers                                                 #
    # ================================================================ #

    def _validate_required_fields(
        self, data: Dict[str, Any], required: list[str]
    ) -> None:
        for field in required:
            if field not in data or not data[field]:
                raise BadRequestError(
                    f"Field '{field}' adalah required dan tidak boleh kosong"
                )

    def _validate_tahun(self, tahun: int) -> None:
        if not isinstance(tahun, int):
            raise BadRequestError("Tahun harus berupa integer")

        current_year = 2026
        if tahun < 2000 or tahun > current_year + 5:
            raise BadRequestError(
                f"Tahun harus antara 2000 dan {current_year + 5}"
            )
