from typing import Optional
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from model.Chatbot import Chatbot, AuthorityEnum
from repository.chatbotRepository import ChatbotRepository
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
)


class ChatbotService:
    def __init__(self, db: AsyncSession) -> None:  # ← AsyncSession
        self.repo: ChatbotRepository = ChatbotRepository(db)

    # ─── Helper ───────────────────────────────────────────────────────────────

    async def _get_or_404(self, chatbot_id: UUID) -> Chatbot:
        chatbot = await self.repo.get_by_id(chatbot_id)
        if not chatbot:
            raise HTTPException(
                status_code=404,
                detail=f"Chatbot id={chatbot_id} tidak ditemukan."
            )
        return chatbot

    async def _check_nama_unique(self, nama: str, exclude_id: Optional[UUID] = None) -> None:
        existing = await self.repo.get_by_nama(nama)
        if existing and existing.id != exclude_id:
            raise HTTPException(
                status_code=409,
                detail=f"Nama chatbot '{nama}' sudah digunakan."
            )

    async def _enforce_single_active_per_otoritas(
        self,
        otoritas: AuthorityEnum,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        await self.repo.deactivate_active_by_otoritas(otoritas, exclude_id=exclude_id)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    async def get_all(
        self,
        page: int = 1,
        limit: int = 10,
        otoritas: Optional[AuthorityEnum] = None,
        search: Optional[str] = None,
    ) -> dict:
        chatbots, total = await self.repo.get_all(page, limit, otoritas, search)
        total_pages = max(1, -(-total // limit))  # ceiling division

        return {
            "data": [ChatbotResponse.model_validate(c) for c in chatbots],
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
        }

    async def get_by_id(self, chatbot_id: UUID) -> Chatbot:
        return await self._get_or_404(chatbot_id)

    async def create(self, payload: ChatbotCreate) -> Chatbot:
        await self._check_nama_unique(payload.nama_chatbot)
        await self._enforce_single_active_per_otoritas(payload.otoritas)
        return await self.repo.create(payload)

    async def update(self, chatbot_id: UUID, payload: ChatbotUpdate) -> Chatbot:
        existing = await self._get_or_404(chatbot_id)
        if payload.nama_chatbot:
            await self._check_nama_unique(payload.nama_chatbot, exclude_id=chatbot_id)

        target_otoritas = payload.otoritas if payload.otoritas is not None else existing.otoritas
        target_is_active = payload.is_active if payload.is_active is not None else existing.is_active
        if target_is_active:
            await self._enforce_single_active_per_otoritas(
                target_otoritas,
                exclude_id=chatbot_id,
            )

        return await self.repo.update(payload)

    async def delete(self, chatbot_id: UUID, hard: bool = False) -> dict:
        await self._get_or_404(chatbot_id)
        if hard:
            await self.repo.hard_delete()
            return {"message": f"Chatbot id={chatbot_id} berhasil dihapus permanen.", "success": True}
        await self.repo.soft_delete()
        return {"message": f"Chatbot id={chatbot_id} berhasil dinonaktifkan.", "success": True}
