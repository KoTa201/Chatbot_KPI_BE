from typing import Optional
from uuid import UUID
from fastapi import Depends
from sqlalchemy.orm import Session

from sqlalchemy.ext.asyncio import AsyncSession
from databaseConfig import get_db
from model.Chatbot import AuthorityEnum
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
    MessageResponse,
)
from service.chatbotService import ChatbotService


def get_chatbot_service(db: Session = Depends(get_db)) -> ChatbotService:
    """Factory dependency: inject DB session ke service."""
    return ChatbotService(db)


class ChatbotController:
    """
    Controller: titik masuk dari router ke service.
    Bertanggung jawab memanggil service dan mengembalikan response schema.
    """

    def __init__(self, db: AsyncSession):
        self.service: ChatbotService = ChatbotService(db)

    async def list_chatbots(
        self,
        page: int,
        page_size: int,
        otoritas: Optional[AuthorityEnum],
        search: Optional[str],
    ) -> ChatbotListResponse:
        return await self.service.get_all(page, page_size, otoritas, search)

    async def get_chatbot(self, chatbot_id: UUID) -> ChatbotResponse:
        return await self.service.get_by_id(chatbot_id)

    async def create_chatbot(self, payload: ChatbotCreate) -> ChatbotResponse:
        return await self.service.create(payload)

    async def update_chatbot(
        self,
        chatbot_id: UUID,
        payload: ChatbotUpdate,
    ) -> ChatbotResponse:
        return await self.service.update(chatbot_id, payload)

    async def delete_chatbot(
        self,
        chatbot_id: UUID,
        hard: bool,
    ) -> MessageResponse:
        result = await self.service.delete(chatbot_id, hard=hard)
        return MessageResponse(**result)
