"""
repository/trackerSourceRepository.py
"""
from typing import Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.TrackerSource import TrackerSourceORM


class TrackerSourceRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[TrackerSourceORM]:
        result = await self.db.execute(
            select(TrackerSourceORM).order_by(TrackerSourceORM.created_at)
        )
        return list(result.scalars().all())

    async def get_active_scheduled(self) -> list[TrackerSourceORM]:
        result = await self.db.execute(
            select(TrackerSourceORM)
            .where(TrackerSourceORM.is_active == True)
            .where(TrackerSourceORM.is_scheduled == True)
            .order_by(TrackerSourceORM.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, source_id: UUID) -> Optional[TrackerSourceORM]:
        result = await self.db.execute(
            select(TrackerSourceORM).where(TrackerSourceORM.id == source_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self, name: str, sheet_url: str, is_scheduled: bool
    ) -> TrackerSourceORM:
        source = TrackerSourceORM(
            name=name, sheet_url=sheet_url, is_scheduled=is_scheduled
        )
        self.db.add(source)
        try:
            await self.db.commit()
            await self.db.refresh(source)
            return source
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500, detail=f"Gagal simpan tracker source: {str(e)}"
            )

    async def update(
        self, source_id: UUID, updates: dict
    ) -> Optional[TrackerSourceORM]:
        source = await self.get_by_id(source_id)
        if not source:
            return None
        for key, val in updates.items():
            setattr(source, key, val)
        try:
            await self.db.commit()
            await self.db.refresh(source)
            return source
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500, detail=f"Gagal update tracker source: {str(e)}"
            )

    async def delete(self, source_id: UUID) -> bool:
        source = await self.get_by_id(source_id)
        if not source:
            return False
        try:
            await self.db.delete(source)
            await self.db.commit()
            return True
        except Exception as e:
            await self.db.rollback()
            raise HTTPException(
                status_code=500, detail=f"Gagal hapus tracker source: {str(e)}"
            )
