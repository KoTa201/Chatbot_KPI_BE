"""
repository/kpiMasterRepository.py
DB operations for KPI Master.

Changelog v4 (many-to-many):
  - user_id dihapus dari _UPSERT_COLS dan dari skema records.
  - upsert_by_group() kini menerima key "user_ids" (list[UUID]) di setiap
    record, di-strip sebelum INSERT ke kpi_master_records, lalu di-sync
    ke tabel junction kpi_master_users setelah upsert selesai.
  - Tambah _sync_pic_users(): hapus asosiasi lama untuk KPI yang di-upsert,
    lalu insert asosiasi baru. Dijalankan dalam transaksi yang sama.
  - Semua operasi masih dibungkus dalam satu commit.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster, kpi_master_users

# Kolom yang diupdate saat conflict (group_id & kpi_name adalah conflict key)
_UPSERT_COLS = [
    "category",
    "definisi_operasional",
    "target",
    "achieve",
    "partial",
    "fail",
    # user_id dihapus — PIC kini dikelola via tabel junction kpi_master_users
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
        Upsert KPI Master + sync PIC users ke tabel junction.

        Tiap record boleh menyertakan key ``user_ids`` (list[UUID]).
        Key ini di-strip sebelum INSERT ke kpi_master_records dan
        digunakan untuk sync kpi_master_users.

        Records HARUS sudah menyertakan 'group_id' (UUID).

        Returns:
            Jumlah records yang di-upsert.
        """
        if not records:
            self.kpi_masters = []
            self.upsert_count = 0
            return 0

        # ── Pisahkan user_ids dari payload DB ───────────────────────────
        # tahun disimpan di kpi_groups, bukan di kpi_master_records.
        # dict: (group_id_str, kpi_name) → list[UUID]
        user_ids_map: dict[tuple[str, str], list[UUID]] = {}
        clean_records: list[dict] = []

        for r in records:
            r = dict(r)                          # shallow copy agar tidak mutasi caller
            user_ids: list[UUID] = r.pop("user_ids", None) or []
            r.pop("tahun", None)
            user_ids_map[(str(r["group_id"]), r["kpi_name"])] = user_ids
            clean_records.append(r)

        self.kpi_masters = clean_records

        try:
            # ── Upsert KPI Master rows ───────────────────────────────────
            stmt = pg_insert(KPIMaster).values(clean_records)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_kpimaster_group_name",   # (group_id, kpi_name)
                set_={col: stmt.excluded[col] for col in _UPSERT_COLS},
            )
            await self.db.execute(stmt)

            # ── Ambil ID aktual dari DB setelah upsert ───────────────────
            # Perlu untuk mencocokkan kpi_name → kpi_master_id di junction.
            group_id = clean_records[0]["group_id"]
            kpi_names = [r["kpi_name"] for r in clean_records]

            id_result = await self.db.execute(
                select(KPIMaster.id, KPIMaster.kpi_name)
                .where(
                    KPIMaster.group_id == group_id,
                    KPIMaster.kpi_name.in_(kpi_names),
                )
            )
            # {kpi_name: kpi_master_id}
            name_to_id: dict[str, UUID] = {row.kpi_name: row.id for row in id_result}

            # ── Sync PIC users di junction table ─────────────────────────
            await self._sync_pic_users(name_to_id, user_ids_map)

            await self.db.commit()
            self.upsert_count = len(clean_records)
            return self.upsert_count

        except HTTPException:
            await self.db.rollback()
            self.kpi_masters = []
            self.upsert_count = 0
            raise

        except Exception as e:
            await self.db.rollback()
            self.kpi_masters = []
            self.upsert_count = 0
            raise HTTPException(
                status_code=500,
                detail=(
                    "Gagal simpan KPI Master ke database. "
                    "Periksa data input dan constraint di database."
                ),
            )

    async def get_id_map_by_names(
        self,
        kpi_names: list[str],
        tahun: int | None = None,
    ) -> dict[str, UUID]:
        if not kpi_names:
            return {}

        query = select(KPIMaster.id, KPIMaster.kpi_name).where(
            KPIMaster.kpi_name.in_(kpi_names)
        )
        if tahun:
            query = query.join(KPIGroup, KPIMaster.group_id == KPIGroup.id).where(
                KPIGroup.group_type.in_(["master", "MASTER"]),
                KPIGroup.tahun == tahun,
            )

        result = await self.db.execute(query)
        master_map: dict[str, UUID] = {}
        for row in result.fetchall():
            if row.kpi_name not in master_map:
                master_map[row.kpi_name] = row.id
        return master_map

    # ================================================================ #
    #  DELETE                                                           #
    # ================================================================ #

    async def delete_by_group_id(self, group_id) -> int:
        """
        Hapus seluruh KPI Master (beserta junction rows-nya via CASCADE)
        yang terkait dengan satu KPI Group.

        Dipakai saat re-ingest agar data lama dibersihkan sebelum records
        baru dimasukkan kembali.

        Returns:
            Jumlah baris kpi_master_records yang dihapus.
        """
        try:
            stmt = delete(KPIMaster).where(KPIMaster.group_id == group_id)
            result = await self.db.execute(stmt)
            await self.db.commit()
            return result.rowcount or 0

        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Master berdasarkan group_id: {str(e)}",
            )

    # ================================================================ #
    #  PRIVATE                                                          #
    # ================================================================ #

    async def _sync_pic_users(
        self,
        name_to_id: dict[str, UUID],
        user_ids_map: dict[tuple[str, str], list[UUID]],
    ) -> None:
        """
        Hapus asosiasi PIC lama untuk KPI yang di-upsert, lalu insert baru.

        Dipanggil di dalam transaksi aktif (sebelum commit).
        Tidak melakukan commit sendiri.

        Args:
            name_to_id    — {kpi_name: kpi_master_id} dari hasil SELECT setelah upsert.
            user_ids_map  — {(group_id_str, kpi_name): [user_id, ...]} dari records input.
        """
        kpi_master_ids = list(name_to_id.values())
        if not kpi_master_ids:
            return

        # Hapus semua asosiasi lama untuk KPI yang baru saja di-upsert
        await self.db.execute(
            delete(kpi_master_users).where(
                kpi_master_users.c.kpi_master_id.in_(kpi_master_ids)
            )
        )

        # Bangun baris baru
        assoc_rows: list[dict] = []
        for (_, kpi_name), user_ids in user_ids_map.items():
            kpi_master_id = name_to_id.get(kpi_name)
            if kpi_master_id is None or not user_ids:
                continue
            for uid in user_ids:
                assoc_rows.append({
                    "kpi_master_id": kpi_master_id,
                    "user_id":       uid,
                })

        if assoc_rows:
            await self.db.execute(
                insert(kpi_master_users).values(assoc_rows)
            )
