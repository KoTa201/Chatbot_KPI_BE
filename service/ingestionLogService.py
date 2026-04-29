"""
service/ingestionLogService.py
Service untuk menangani logika bisnis ingestion logs.
"""

import re
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.Base import GroupTypeEnum
from model.IngestionLog import IngestionLogORM
from model.KPIGroup import KPIGroupORM


class IngestionLogService:
    """Service untuk ingestion log operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_ingestion_logs(
        self,
        page: int,
        limit: int,
        group_type: Optional[str] = None,
    ) -> dict:
        group_type_filter = self._normalize_group_type(group_type)
        offset = (page - 1) * limit

        count_query = select(func.count()).select_from(IngestionLogORM).join(
            KPIGroupORM,
            KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )

        if group_type_filter is not None:
            count_query = count_query.where(KPIGroupORM.group_type == group_type_filter)

        total_result = await self.db.execute(count_query)
        total_count = int(total_result.scalar_one() or 0)

        query = select(IngestionLogORM, KPIGroupORM).join(
            KPIGroupORM,
            KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )

        if group_type_filter is not None:
            query = query.where(KPIGroupORM.group_type == group_type_filter)

        query = query.order_by(IngestionLogORM.created_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(query)
        rows = result.all()

        logs_payload = [
            self._format_log_response(log, group)
            for log, group in rows
        ]

        return {
            "total": total_count,
            "logs": logs_payload,
        }


    def _format_log_response(
        self,
        log: IngestionLogORM,
        group: KPIGroupORM | None = None,
    ) -> dict:
        sheet_name = group.nama_grup if group else str(log.kpi_group_id)
        nama_orang = None

        if group and group.group_type == GroupTypeEnum.TRACKER:
            nama_orang = self._extract_nama_orang(group.nama_grup)

        source_type = None
        if group:
            if group.group_type == GroupTypeEnum.MASTER:
                source_type = "kpi_master"
            elif group.group_type == GroupTypeEnum.TRACKER:
                source_type = "kpi_tracker"

        return {
            "id": log.id,
            "sheet_name": sheet_name,
            "nama_orang": nama_orang,
            "total_rows": log.total_rows,
            "ingested": log.ingested_count,
            "failed": log.failed_count,
            "status": log.status,
            "source_type": source_type,
            "source_id": log.kpi_group_id,
            "created_at": log.created_at,
        }

    @staticmethod
    def _normalize_group_type(group_type: Optional[str]) -> Optional[GroupTypeEnum]:
        if group_type is None:
            return None

        # Backward compatibility: frontend lama pakai source_type=kpi_tracker|kpi_master
        if group_type in {"tracker", "kpi_tracker"}:
            return GroupTypeEnum.TRACKER
        if group_type in {"master", "kpi_master"}:
            return GroupTypeEnum.MASTER
        return None

    @staticmethod
    def _extract_nama_orang(nama_grup: Optional[str]) -> Optional[str]:
        if not nama_grup:
            return None
        match = re.match(r"^KPI_Tracker_(.+?)_(20\d{2})$", nama_grup)
        if match:
            return match.group(1).replace("_", " ").strip()
        return None
