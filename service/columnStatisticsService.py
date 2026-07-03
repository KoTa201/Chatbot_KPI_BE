import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster
from model.KPITracker import KPITracker
from model.NlSqlStatsCache import NlSqlStatsCache
from model.User import User

_CACHE_ROW_ID = 1


class ColumnStatisticsService:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    # ---- kolom yang dihitung statistiknya (single source of truth) ---- #
    _numeric_columns = [
        ("kpi_groups", "tahun", KPIGroup.tahun),
        ("kpi_tracker_records", "bulan_num", KPITracker.bulan_num),
    ]
    _text_columns = [
        ("users", "full_name", User.full_name),
        ("users", "role", User.role),
        ("kpi_groups", "nama_grup", KPIGroup.nama_grup),
        ("kpi_groups", "group_type", KPIGroup.group_type),
        ("kpi_groups", "sheet_name", KPIGroup.sheet_name),
        ("kpi_master_records", "category", KPIMaster.category),
        ("kpi_master_records", "kpi_name", KPIMaster.kpi_name),
        ("kpi_master_records", "target", KPIMaster.target),
        ("kpi_master_records", "achieve", KPIMaster.achieve),
        ("kpi_master_records", "partial", KPIMaster.partial),
        ("kpi_master_records", "fail", KPIMaster.fail),
        ("kpi_tracker_records", "realisasi", KPITracker.realisasi),
        ("kpi_tracker_records", "keterangan", KPITracker.keterangan),
    ]
    _boolean_columns = [
        ("users", "is_active", User.is_active),
        ("kpi_groups", "is_active", KPIGroup.is_active),
    ]

    # ================================================================== #
    #  Read path (inference): baca cache, tanpa jalankan ulang query      #
    # ================================================================== #

    async def get_statistics_text(self) -> str:
        """
        Kembalikan teks statistik siap-prompt dari cache (satu query baca).
        Kalau cache belum pernah diisi (first run / belum ada ingestion),
        fallback hitung sekali via refresh_statistics().
        """
        row = await self.db.get(NlSqlStatsCache, _CACHE_ROW_ID)
        if row is None:
            stats = await self.refresh_statistics()
        else:
            stats = json.loads(row.stats_json)
        return self._format_statistics_text(stats)

    # ================================================================== #
    #  Write path (ingestion): compute-once lalu simpan                   #
    # ================================================================== #

    async def refresh_statistics(self) -> dict:
        """
        Hitung statistik lalu upsert ke baris singleton (id=1).
        Dipanggil di akhir pipeline ingestion. Upsert aman kalau baris sudah
        ada (get-then-update) dan tahan race concurrent-insert.
        """
        stats = await self._compute_statistics()
        payload = json.dumps(stats, default=str)
        now = datetime.now(timezone.utc)

        row = await self.db.get(NlSqlStatsCache, _CACHE_ROW_ID)
        if row is None:
            self.db.add(
                NlSqlStatsCache(id=_CACHE_ROW_ID, stats_json=payload, computed_at=now)
            )
        else:
            row.stats_json = payload
            row.computed_at = now

        try:
            await self.db.commit()
        except IntegrityError:
            # Proses ingestion lain menyisipkan baris id=1 lebih dulu — update saja.
            await self.db.rollback()
            row = await self.db.get(NlSqlStatsCache, _CACHE_ROW_ID)
            if row is not None:
                row.stats_json = payload
                row.computed_at = now
                await self.db.commit()

        return stats

    async def _compute_statistics(self) -> dict:
        """
        Logic inti (loop numeric/text/boolean). Hasil dict terstruktur agar bisa
        di-serialize ke JSON dan diformat ulang jadi teks yang identik.
        """
        stats: dict[str, dict[str, Any]] = {}

        for table_name, column_name, column in self._numeric_columns:
            result = await self.db.execute(
                select(
                    func.avg(column),
                    func.min(column),
                    func.max(column),
                    func.count(column),
                    func.sum(case((column != 0, 1), else_=0)),
                )
            )
            mean, minimum, maximum, non_null, non_zero = result.one()
            stats[f"{table_name}.{column_name}"] = {
                "type": "numeric",
                "mean": self._format_value(mean),
                "min": self._format_value(minimum),
                "max": self._format_value(maximum),
                "non_null": non_null,
                "non_zero": non_zero or 0,
            }

        for table_name, column_name, column in self._text_columns:
            values_result = await self.db.execute(
                select(distinct(column))
                .where(column.is_not(None))
                .where(column != "")
                .order_by(column)
                .limit(30)
            )
            unique_values = [self._format_value(row[0]) for row in values_result.all()]
            counts_result = await self.db.execute(
                select(
                    func.count(column),
                    func.sum(case((column != "", 1), else_=0)),
                )
            )
            non_null, non_zero = counts_result.one()
            stats[f"{table_name}.{column_name}"] = {
                "type": "text",
                "unique": unique_values,
                "non_null": non_null,
                "non_zero": non_zero or 0,
            }

        for table_name, column_name, column in self._boolean_columns:
            values_result = await self.db.execute(
                select(distinct(column))
                .where(column.is_not(None))
                .order_by(column)
                .limit(30)
            )
            unique_values = [self._format_value(row[0]) for row in values_result.all()]
            counts_result = await self.db.execute(
                select(
                    func.count(column),
                    func.sum(case((column.is_(True), 1), else_=0)),
                )
            )
            non_null, non_zero = counts_result.one()
            stats[f"{table_name}.{column_name}"] = {
                "type": "boolean",
                "unique": unique_values,
                "non_null": non_null,
                "non_zero": non_zero or 0,
            }

        return stats

    @staticmethod
    def _format_statistics_text(stats: dict) -> str:
        """
        Ubah dict statistik jadi teks siap-prompt. Format harus identik dengan
        output lama build_nl_to_sql_statistics() agar prompt LLM tidak berubah.
        """
        lines: list[str] = []
        for key, entry in stats.items():
            if entry.get("type") == "numeric":
                lines.append(
                    f"{key}: mean={entry['mean']}, min={entry['min']}, "
                    f"max={entry['max']}, non_null={entry['non_null']}, "
                    f"non_zero={entry['non_zero']}"
                )
            else:
                lines.append(
                    f"{key}: unique={entry['unique']}, "
                    f"non_null={entry['non_null']}, non_zero={entry['non_zero']}"
                )
        return "\n".join(lines)

    @staticmethod
    def _format_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, float):
            return round(value, 4)
        if hasattr(value, "value"):
            return value.value
        return value
