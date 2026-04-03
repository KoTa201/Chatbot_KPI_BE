from typing import Optional
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
        self.repo = ChatbotRepository(db)

    # ─── Helper ───────────────────────────────────────────────────────────────

    async def _get_or_404(self, chatbot_id: int) -> Chatbot:
        chatbot = await self.repo.get_by_id(chatbot_id)
        if not chatbot:
            raise HTTPException(
                status_code=404,
                detail=f"Chatbot id={chatbot_id} tidak ditemukan."
            )
        return chatbot

    async def _check_nama_unique(self, nama: str, exclude_id: Optional[int] = None) -> None:
        existing = await self.repo.get_by_nama(nama)
        if existing and existing.id != exclude_id:
            raise HTTPException(
                status_code=409,
                detail=f"Nama chatbot '{nama}' sudah digunakan."
            )

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    async def get_all(
        self,
        page: int = 1,
        page_size: int = 10,
        otoritas: Optional[AuthorityEnum] = None,
        search: Optional[str] = None,
    ) -> ChatbotListResponse:
        skip = (page - 1) * page_size
        chatbots, total = await self.repo.get_all(skip, page_size, otoritas, search)
        total_pages = max(1, -(-total // page_size))  # ceiling division

        return ChatbotListResponse(
            data=[ChatbotResponse.model_validate(c) for c in chatbots],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    async def get_by_id(self, chatbot_id: int) -> ChatbotResponse:
        chatbot = await self._get_or_404(chatbot_id)
        return ChatbotResponse.model_validate(chatbot)

    async def create(self, payload: ChatbotCreate) -> ChatbotResponse:
        await self._check_nama_unique(payload.nama_chatbot)
        chatbot = await self.repo.create(payload)
        return ChatbotResponse.model_validate(chatbot)

    async def update(self, chatbot_id: int, payload: ChatbotUpdate) -> ChatbotResponse:
        chatbot = await self._get_or_404(chatbot_id)
        if payload.nama_chatbot:
            await self._check_nama_unique(payload.nama_chatbot, exclude_id=chatbot_id)
        updated = await self.repo.update(chatbot, payload)
        return ChatbotResponse.model_validate(updated)

    async def delete(self, chatbot_id: int, hard: bool = False) -> dict:
        chatbot = await self._get_or_404(chatbot_id)
        if hard:
            await self.repo.hard_delete(chatbot)
            return {"message": f"Chatbot id={chatbot_id} berhasil dihapus permanen.", "success": True}
        await self.repo.soft_delete(chatbot)
        return {"message": f"Chatbot id={chatbot_id} berhasil dinonaktifkan.", "success": True}
