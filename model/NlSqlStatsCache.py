"""
model/NlSqlStatsCache.py

Cache singleton untuk statistik kolom NL-to-SQL.
- Selalu tepat satu baris (id=1).
- stats_json: hasil ColumnStatisticsService._compute_statistics() sebagai JSON string.
- computed_at: kapan statistik terakhir dihitung (di akhir pipeline ingestion).

Dibaca saat inference (text-to-SQL) supaya ~38 query statistik tidak dijalankan
ulang setiap request. Bukan CREATE VIEW — caching di level aplikasi agar portable.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from model.Base import Base


class NlSqlStatsCache(Base):
    __tablename__ = "nl_sql_stats_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    stats_json: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<NlSqlStatsCache id={self.id} computed_at={self.computed_at}>"
