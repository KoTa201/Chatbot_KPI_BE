"""Repository operasi database untuk ingestion KPI Tracker."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from model.KPITracker import KPITrackerORM


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

        orm_records = [KPITrackerORM(**r) for r in records]
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

    async def delete_kpi_records_by_group_and_period(
        self,
        group_id: UUID,
        tahun: int,
        bulan_num: int | None = None,
    ) -> int:
        """
        Hapus records tracker untuk kombinasi group + periode tertentu.
        Dipakai untuk idempotent re-ingest per bulan/tahun.
        """
        try:
            stmt = delete(KPITrackerORM).where(
                KPITrackerORM.group_id == group_id,
                KPITrackerORM.tahun == tahun,
            )

            if bulan_num is None:
                stmt = stmt.where(KPITrackerORM.bulan_num.is_(None))
            else:
                stmt = stmt.where(KPITrackerORM.bulan_num == bulan_num)

            result = await self.db.execute(stmt)
            await self.db.flush()
            return result.rowcount or 0

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Tracker records untuk group={group_id}, tahun={tahun}, bulan={bulan_num}: {str(e)}",
            )
