"""
repository/kpiMasterRepository.py
DB operations for KPI Master ingestion — upsert by (tahun, kpi_name).
"""

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIMaster import KPIMasterORM

_UPSERT_COLS = [
    "category", "definisi_operasional", "dihitung", "tidak_dihitung",
    "rumus", "target", "sumber_data", "achieve", "partial", "fail",
    "responsibility_persons", "source_sheet_id", "source_sheet_name",
]


class KPIMasterRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_by_tahun(self, records: list[dict]) -> int:
        """
        Upsert KPI Master records. Conflict on (tahun, kpi_name) → update.
        Returns count of upserted records.
        """
        if not records:
            return 0
        try:
            stmt = insert(KPIMasterORM).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["tahun", "kpi_name"],
                set_={col: stmt.excluded[col] for col in _UPSERT_COLS},
            )
            await self.db.execute(stmt)
            await self.db.commit()
            return len(records)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI Master ke database: {str(e)}",
            )
