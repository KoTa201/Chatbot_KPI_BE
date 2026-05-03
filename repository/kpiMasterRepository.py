"""
repository/kpiMasterRepository.py
DB operations for KPI Master — disesuaikan dengan model baru (group_id FK).

Perubahan utama dari versi sebelumnya:
  - Conflict key upsert: (group_id, kpi_name) via constraint "uq_kpimaster_group_name"
    menggantikan (tahun, kpi_name).
  - Kolom source_sheet_id / source_sheet_name DIHAPUS dari _UPSERT_COLS —
    info sheet kini ada di kpi_groups, bukan di setiap baris master.
  - Semua grouped queries di-JOIN ke kpi_groups agar bisa group by sheet info.
  - delete_by_source_sheet_name: resolve group dulu lewat JOIN, baru hapus masters.

Interface publik (nama metode & struktur return) TIDAK BERUBAH
agar controller dan service tidak perlu tahu detail JOIN internal.
"""

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIMaster import KPIMasterORM

# Kolom yang diupdate saat conflict (group_id & kpi_name adalah conflict key, tidak diupdate)
_UPSERT_COLS = [
    "tahun",
    "category",
    "definisi_operasional",
    "target",
    "achieve",
    "partial",
    "fail",
    "user_id",
]


class KPIMasterRepository:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.kpi_masters:  list[dict] = []
        self.upsert_count: int = 0

    # ================================================================ #
    #  UPSERT                                                           #
    # ================================================================ #

    async def upsert_by_group(self, records: list[dict]) -> int:
        """
        Upsert KPI Master. Conflict on (group_id, kpi_name) → update konten KPI.

        Records HARUS sudah menyertakan 'group_id' (UUID) sebelum dipanggil.
        group_id diisi oleh KPIMasterIngestionService setelah KPIGroup dibuat.

        Returns:
            Jumlah records yang di-upsert.
        """
        if not records:
            self.kpi_masters = []
            self.upsert_count = 0
            return 0

        self.kpi_masters = records

        try:
            stmt = insert(KPIMasterORM).values(records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_kpimaster_group_name",   # (group_id, kpi_name)
                set_={col: stmt.excluded[col] for col in _UPSERT_COLS},
            )
            await self.db.execute(stmt)
            await self.db.commit()
            self.upsert_count = len(records)
            return self.upsert_count

        except Exception as e:
            await self.db.rollback()
            self.kpi_masters = []
            self.upsert_count = 0
            raise HTTPException(
                status_code=500,
                detail=f"Gagal simpan KPI Master ke database: {str(e)}",
            )

    async def delete_by_group_id(self, group_id) -> int:
        """
        Hapus seluruh KPI Master yang terkait dengan satu KPI Group.

        Dipakai saat re-ingest agar data lama dibersihkan sebelum records baru
        dimasukkan kembali.

        Returns:
            Jumlah baris yang dihapus.
        """
        try:
            stmt = delete(KPIMasterORM).where(KPIMasterORM.group_id == group_id)
            result = await self.db.execute(stmt)
            await self.db.commit()
            return int(result.rowcount or 0)

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Master berdasarkan group_id: {str(e)}",
            )
