from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.KPIGroup import KPIGroup
from model.KPIMaster import KPIMaster
from model.KPITracker import KPITracker
from model.User import User
from typing import cast as type_cast

class ColumnStatisticsService:
    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def build_nl_to_sql_statistics(self) -> str:
        lines: list[str] = []

        numeric_columns = [
            ("kpi_groups", "tahun", KPIGroup.tahun),
            ("kpi_tracker_records", "bulan_num", KPITracker.bulan_num),
        ]
        text_columns = [
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
        boolean_columns = [
            ("users", "is_active", User.is_active),
            ("kpi_groups", "is_active", KPIGroup.is_active),
        ]

        for table_name, column_name, column in numeric_columns:
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
            lines.append(
                f"{table_name}.{column_name}: mean={self._format_value(mean)}, min={self._format_value(minimum)}, max={self._format_value(maximum)}, non_null={non_null}, non_zero={non_zero or 0}"
            )

        for table_name, column_name, column in text_columns:
            values_result = await self.db.execute(
                select(distinct(column))
                .where(column.is_not(None))
                .where(column != "")
                .order_by(column)
                .limit(30)
            )
            unique_values = [self._format_value(row[0]) for row in values_result.all()]
            non_null_result = await self.db.execute(select(func.count(column)))
            non_zero_result = await self.db.execute(
                select(func.count()).select_from(column.class_).where(column.is_not(None)).where(column != "")
            )
            non_null = non_null_result.scalar_one()
            non_zero = non_zero_result.scalar_one()
            lines.append(
                f"{table_name}.{column_name}: unique={unique_values}, non_null={non_null}, non_zero={non_zero}"
            )

        for table_name, column_name, column in boolean_columns:
            values_result = await self.db.execute(
                select(distinct(column))
                .where(column.is_not(None))
                .order_by(column)
                .limit(30)
            )
            unique_values = [self._format_value(row[0]) for row in values_result.all()]
            non_null_result = await self.db.execute(select(func.count(column)))
            model_class = type_cast(type, column.class_)
            non_zero_result = await self.db.execute(
                select(func.count()).select_from(model_class).where(column.is_(True))
            )
            non_null = non_null_result.scalar_one()
            non_zero = non_zero_result.scalar_one()
            lines.append(
                f"{table_name}.{column_name}: unique={unique_values}, non_null={non_null}, non_zero={non_zero}"
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
