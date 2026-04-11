"""
repository/kpiMasterRepository.py
DB operations for KPI Master ingestion — upsert by (tahun, kpi_name).
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, desc
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
        self.kpi_masters: list[KPIMasterORM] = []
        self.upsert_count: int = 0

    async def upsert_by_tahun(self, records: list[dict]) -> int:
        """
        Upsert KPI Master records. Conflict on (tahun, kpi_name) → update.
        Returns count of upserted records.
        """
        if not records:
            self.kpi_masters = []
            self.upsert_count = 0
            return 0

        # Track records dalam instance state
        self.kpi_masters = records

        try:
            stmt = insert(KPIMasterORM).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["tahun", "kpi_name"],
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

    # ================================================================ #
    #  GROUP/AGGREGATE Operations (Grouped by Source Sheet Name)        #
    # ================================================================ #

    async def get_grouped_by_source_sheet_name(self,
                                               skip: int = 0,
                                               limit: int = 100) -> list[dict]:
        """
        Ambil KPI Masters yang dikelompokkan berdasarkan source_sheet_name (nama file).
        Setiap group menampilkan: source_sheet_name, total_count, tahun_list, categories, kpi_count, last_updated.

        Args:
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            List[dict] dengan group info
        """
        try:
            from sqlalchemy import func

            query = select(
                KPIMasterORM.source_sheet_name,
                func.count(KPIMasterORM.id).label("total_count"),
                func.array_agg(KPIMasterORM.tahun,
                               distinct=True).label("tahun_list"),
                func.array_agg(KPIMasterORM.category,
                               distinct=True).label("categories"),
                func.count(KPIMasterORM.kpi_name,
                           distinct=True).label("kpi_count"),
                func.max(KPIMasterORM.created_at).label("last_updated"),
            ).group_by(
                KPIMasterORM.source_sheet_name
            ).order_by(
                desc(func.max(KPIMasterORM.created_at))
            ).offset(skip).limit(limit)

            result = await self.db.execute(query)
            rows = result.fetchall()

            return [
                {
                    "source_sheet_name": row.source_sheet_name or "UNKNOWN",
                    "total_count": row.total_count or 0,
                    "tahun_list": list(row.tahun_list) if row.tahun_list else [],
                    "categories": list(row.categories) if row.categories else [],
                    "kpi_count": row.kpi_count or 0,
                    "last_updated": row.last_updated,
                }
                for row in rows
            ]
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters: {str(e)}",
            )

    async def get_grouped_by_source_sheet_name_with_filters(self,
                                                            tahun: Optional[int] = None,
                                                            category: Optional[str] = None,
                                                            skip: int = 0,
                                                            limit: int = 100) -> list[dict]:
        """
        Ambil KPI Masters grouped by source_sheet_name dengan optional filters.

        Args:
            tahun: Filter by tahun
            category: Filter by category
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            List[dict] dengan filtered group info
        """
        try:
            # First, get distinct source_sheet_names that match filters
            base_query = select(KPIMasterORM)

            if tahun:
                base_query = base_query.where(KPIMasterORM.tahun == tahun)
            if category:
                base_query = base_query.where(
                    KPIMasterORM.category.ilike(f"%{category}%"))

            filtered_result = await self.db.execute(base_query)
            filtered_masters = filtered_result.scalars().all()

            # Group by source_sheet_name from filtered results
            grouped_data = {}
            for master in filtered_masters:
                sheet_name = master.source_sheet_name or "UNKNOWN"
                if sheet_name not in grouped_data:
                    grouped_data[sheet_name] = {
                        "source_sheet_name": sheet_name,
                        "tahun_set": set(),
                        "category_set": set(),
                        "kpi_names": set(),
                        "count": 0,
                        "last_updated": None,
                    }

                grouped_data[sheet_name]["tahun_set"].add(master.tahun)
                grouped_data[sheet_name]["category_set"].add(master.category)
                grouped_data[sheet_name]["kpi_names"].add(master.kpi_name)
                grouped_data[sheet_name]["count"] += 1

                if grouped_data[sheet_name]["last_updated"] is None or master.created_at > grouped_data[sheet_name]["last_updated"]:
                    grouped_data[sheet_name]["last_updated"] = master.created_at

            # Convert to list, sort by last_updated, and paginate
            result_list = [
                {
                    "source_sheet_name": group["source_sheet_name"],
                    "total_count": group["count"],
                    "tahun_list": sorted(list(group["tahun_set"])),
                    "categories": sorted(list(group["category_set"])),
                    "kpi_count": len(group["kpi_names"]),
                    "last_updated": group["last_updated"],
                }
                for group in grouped_data.values()
            ]

            # Sort by last_updated descending
            result_list.sort(
                key=lambda x: x["last_updated"] or "1900-01-01", reverse=True)

            # Apply pagination
            return result_list[skip:skip + limit]

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil grouped KPI Masters dengan filters: {str(e)}",
            )

    async def get_detail_masters_by_source_sheet_name(self,
                                                      source_sheet_name: str,
                                                      skip: int = 0,
                                                      limit: int = 100) -> list[KPIMasterORM]:
        """
        Ambil detail masters untuk satu source_sheet_name tertentu (expand group).
        Menampilkan semua individual masters dalam satu file group.

        Args:
            source_sheet_name: Nama file yang dicari
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            List[KPIMasterORM] dengan detail masters
        """
        try:
            query = select(KPIMasterORM).where(
                KPIMasterORM.source_sheet_name.ilike(f"%{source_sheet_name}%")
            ).offset(skip).limit(limit).order_by(
                desc(KPIMasterORM.created_at)
            )

            result = await self.db.execute(query)
            return result.scalars().all()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal ambil detail masters: {str(e)}",
            )

    async def delete_by_source_sheet_name(self, source_sheet_name: str) -> int:
        """
        Hapus semua KPI Master yang memiliki source_sheet_name tertentu.
        Returns count of deleted records.
        """
        try:
            query = select(KPIMasterORM).where(
                KPIMasterORM.source_sheet_name.ilike(f"%{source_sheet_name}%")
            )
            result = await self.db.execute(query)
            masters_to_delete = result.scalars().all()

            if not masters_to_delete:
                return 0

            for master in masters_to_delete:
                await self.db.delete(master)
            await self.db.commit()
            return len(masters_to_delete)
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Gagal hapus KPI Masters: {str(e)}",
            )
