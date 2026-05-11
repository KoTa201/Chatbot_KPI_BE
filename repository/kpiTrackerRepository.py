"""Repository operasi database untuk ingestion KPI Tracker."""

from uuid import UUID
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from model.KPITracker import KPITracker


class KPITrackerRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ================================================================ #
    #  CREATE                                                           #
    # ================================================================ #

    async def bulk_insert_kpi_records(self, records: list[dict]) -> int:
        """
        Bulk-insert KPI Tracker records.

        Records HARUS sudah berisi:
          - group_id      (UUID) — diisi ingestion service setelah KPIGroup dibuat
          - kpi_master_id (UUID | None) — diisi setelah master matching

        Kolom yang TIDAK LAGI ADA di records: nama_kpi, tahun, source_sheet_name.

        Returns:
            Jumlah baris yang berhasil disimpan.
        """
        if not records:
            return 0

        clean_records = []
        for record in records:
            clean = dict(record)
            clean.pop("tahun", None)
            clean_records.append(clean)

        orm_records = [KPITracker(**r) for r in clean_records]
        self.db.add_all(orm_records)
        try:
            await self.db.commit()
            return len(orm_records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI Tracker records ke database: {str(e)}",
            )

    # ================================================================ #
    #  DELETE                                                           #
    # ================================================================ #

    async def delete_kpi_records_by_group_and_period(
        self,
        group_id: UUID,
        bulan_num: Optional[int] = None,
    ) -> int:
        """
        Hapus data tracker existing untuk satu group + periode bulan.

        Tahun berada di kpi_groups, jadi filter record cukup memakai group_id.
        Jika bulan_num None, hapus semua bulan pada group tersebut.
        Returns jumlah baris terhapus.
        """
        try:
            stmt = delete(KPITracker).where(KPITracker.group_id == group_id)

            if bulan_num is not None:
                stmt = stmt.where(KPITracker.bulan_num == bulan_num)

            result = await self.db.execute(stmt)
            await self.db.commit()
            return result.rowcount or 0
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Tracker records untuk periode: {str(e)}",
            )
