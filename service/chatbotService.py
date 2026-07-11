from typing import Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import ConflictError, NotFoundError
from model.Chatbot import Chatbot, AuthorityEnum
from repository.chatbotRepository import ChatbotRepository
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotResponse,
)
from utils.pagination import calculate_total_pages


class ChatbotService:
    def __init__(self, db: AsyncSession) -> None:  # ← AsyncSession
        self.repo: ChatbotRepository = ChatbotRepository(db)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    async def get_all(
        self,
        page: int = 1,
        limit: int = 10,
        authority: Optional[AuthorityEnum] = None,
        search: Optional[str] = None,
    ) -> dict:
        chatbots, total = await self.repo.get_all(page, limit, authority, search)
        total_pages = calculate_total_pages(total, limit, minimum=1)

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
        await self._check_chatbot_name_unique(payload.chatbot_name)
        await self._enforce_single_active_per_authority(payload.authority)
        return await self.repo.create(payload)

    async def update(self, chatbot_id: UUID, payload: ChatbotUpdate) -> Chatbot:
        existing = await self._get_or_404(chatbot_id)
        if payload.chatbot_name:
            await self._check_chatbot_name_unique(payload.chatbot_name, exclude_id=chatbot_id)

        target_authority = payload.authority if payload.authority is not None else existing.authority
        target_is_active = payload.is_active if payload.is_active is not None else existing.is_active
        if target_is_active:
            await self._enforce_single_active_per_authority(
                target_authority,
                exclude_id=chatbot_id,
            )

        return await self.repo.update(existing, payload)

    async def delete(self, chatbot_id: UUID, hard: bool = True) -> dict:
        existing = await self._get_or_404(chatbot_id)
        if hard:
            await self.repo.hard_delete(existing)
            return {"message": f"Chatbot id={chatbot_id} berhasil dihapus permanen.", "success": True}
        await self.repo.soft_delete(existing)
        return {"message": f"Chatbot id={chatbot_id} berhasil dinonaktifkan.", "success": True}

    async def get_active_chatbot_for_role(self, user_role: str):
        chatbot = await self.repo.get_active_by_authority(user_role)
        if chatbot is None:
            raise NotFoundError(f"Tidak ada chatbot aktif yang dikonfigurasi untuk authority user ini.")
        return chatbot

    # ─── Helper ───────────────────────────────────────────────────────────────

    async def _get_or_404(self, chatbot_id: UUID) -> Chatbot:
        chatbot = await self.repo.get_by_id(chatbot_id)
        if not chatbot:
            raise NotFoundError(f"Chatbot id={chatbot_id} tidak ditemukan.")
        return chatbot

    async def _check_chatbot_name_unique(self, chatbot_name: str, exclude_id: Optional[UUID] = None) -> None:
        existing = await self.repo.get_by_chatbot_name(chatbot_name)
        if existing and existing.id != exclude_id:
            raise ConflictError(f"Chatbot name '{chatbot_name}' is already used.")

    async def _enforce_single_active_per_authority(
        self,
        authority: AuthorityEnum,
        exclude_id: Optional[UUID] = None,
    ) -> None:
        await self.repo.deactivate_active_by_authority(authority, exclude_id=exclude_id)

