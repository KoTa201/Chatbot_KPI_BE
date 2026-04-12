"""
controller/kpiGroupController.py

Jembatan antara router (HTTP layer) dan service (business logic).

Tanggung jawab controller:
  - Meneruskan parameter dari router ke KPIGroupService.
  - Tidak mengandung logika bisnis — semua ada di service.
  - Memastikan setiap request mendapat instance service yang fresh
    dengan db session yang benar.

Pola ini konsisten dengan ChatbotController agar mudah di-maintain.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from schema.kpiGroupSchema import (
    KPIGroupCreate,
    KPIGroupUpdate,
    KPIGroupListResponse,
    KPIGroupResponse,
    MessageResponse,
)
from service.kpiGroupService import KPIGroupService


class KPIGroupController:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.service = KPIGroupService(db)

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_groups(
        self,
        page:       int,
        page_size:  int,
        group_type: str | None,
        search:     str | None,
    ) -> KPIGroupListResponse:
        return await self.service.list_groups(
            page=page,
            page_size=page_size,
            group_type=group_type,
            search=search,
        )

    # ─── Get one ──────────────────────────────────────────────────────────────

    async def get_group(self, group_id: UUID) -> KPIGroupResponse:
        return await self.service.get_group(group_id=group_id)

    # ─── Create ───────────────────────────────────────────────────────────────

    async def create_group(self, payload: KPIGroupCreate) -> KPIGroupResponse:
        return await self.service.create_group(payload=payload)

    # ─── Update ───────────────────────────────────────────────────────────────

    async def update_group(
        self,
        group_id: UUID,
        payload:  KPIGroupUpdate,
    ) -> KPIGroupResponse:
        return await self.service.update_group(
            group_id=group_id,
            payload=payload,
        )

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete_group(self, group_id: UUID) -> MessageResponse:
        result = await self.service.delete_group(group_id=group_id)
        return MessageResponse(message=result["message"])
