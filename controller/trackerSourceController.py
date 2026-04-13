"""
controller/trackerSourceController.py
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from repository.trackerSourceRepository import TrackerSourceRepository


class TrackerSourceController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TrackerSourceRepository(db)

    async def get_all(self) -> list[dict]:
        sources = await self.repo.get_all()
        return [self._to_dict(s) for s in sources]

    async def create(self, name: str, sheet_url: str, is_scheduled: bool) -> dict:
        source = await self.repo.create(
            name=name, sheet_url=sheet_url, is_scheduled=is_scheduled
        )
        return self._to_dict(source)

    async def update(self, source_id: UUID, updates: dict) -> dict:
        source = await self.repo.update(source_id, updates)
        if not source:
            raise HTTPException(
                status_code=404, detail="Tracker source tidak ditemukan."
            )
        return self._to_dict(source)

    async def delete(self, source_id: UUID) -> dict:
        deleted = await self.repo.delete(source_id)
        if not deleted:
            raise HTTPException(
                status_code=404, detail="Tracker source tidak ditemukan."
            )
        return {"message": "Source deleted."}

    @staticmethod
    def _to_dict(source) -> dict:
        return {
            "id":           str(source.id),
            "name":         source.name,
            "sheet_url":    source.sheet_url,
            "is_active":    source.is_active,
            "is_scheduled": source.is_scheduled,
            "created_at":   source.created_at,
            "updated_at":   source.updated_at,
        }
