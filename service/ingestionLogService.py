"""
service/ingestionLogService.py
Service untuk menangani logika bisnis ingestion logs.
"""

import re
from datetime import date
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
        limit: int,
        offset: int = 0,
        group_type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict:
        from datetime import datetime, time as dt_time

        group_type_filter = self._normalize_group_type(group_type)

        source_type_value = None
        if group_type_filter is not None:
            source_type_value = "master" if group_type_filter == GroupTypeEnum.MASTER else "tracker"

        base_filters = []
        if source_type_value is not None:
            base_filters.append(IngestionLogORM.source_type == source_type_value)
        if status is not None:
            base_filters.append(IngestionLogORM.status == status)
        if start_date is not None:
            base_filters.append(IngestionLogORM.created_at >= datetime.combine(start_date, dt_time.min))
        if end_date is not None:
            base_filters.append(IngestionLogORM.created_at <= datetime.combine(end_date, dt_time.max))

        count_query = select(func.count()).select_from(IngestionLogORM).outerjoin(
            KPIGroupORM, KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )
        for f in base_filters:
            count_query = count_query.where(f)

        total_result = await self.db.execute(count_query)
        total_count = int(total_result.scalar_one() or 0)

        query = select(IngestionLogORM, KPIGroupORM).outerjoin(
            KPIGroupORM, KPIGroupORM.id == IngestionLogORM.kpi_group_id,
        )
        for f in base_filters:
            query = query.where(f)

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
        sheet_name = group.nama_grup if group else (log.group_name or "—")
        nama_orang = None

        if group and group.group_type == GroupTypeEnum.TRACKER:
            nama_orang = self._extract_nama_orang(group.nama_grup)
        elif not group and log.source_type == "tracker":
            nama_orang = self._extract_nama_orang(log.group_name)

        if group:
            source_type = "kpi_master" if group.group_type == GroupTypeEnum.MASTER else "kpi_tracker"
        elif log.source_type == "master":
            source_type = "kpi_master"
        elif log.source_type == "tracker":
            source_type = "kpi_tracker"
        else:
            source_type = None

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
