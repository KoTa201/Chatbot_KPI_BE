from typing import Optional
from uuid import UUID
from fastapi import Depends
from sqlalchemy.orm import Session

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

    @staticmethod
    async def list_chatbots(
        page: int,
        page_size: int,
        otoritas: Optional[AuthorityEnum],
        search: Optional[str],
        service: ChatbotService,
    ) -> ChatbotListResponse:
        # ← await
        return await service.get_all(page, page_size, otoritas, search)

    @staticmethod
    async def get_chatbot(
        chatbot_id: UUID,
        service: ChatbotService,
    ) -> ChatbotResponse:
        return await service.get_by_id(chatbot_id)  # ← await

    @staticmethod
    async def create_chatbot(
        payload: ChatbotCreate,
        service: ChatbotService,
    ) -> ChatbotResponse:
        return await service.create(payload)  # ← await

    @staticmethod
    async def update_chatbot(
        chatbot_id: UUID,
        payload: ChatbotUpdate,
        service: ChatbotService,
    ) -> ChatbotResponse:
        return await service.update(chatbot_id, payload)  # ← await

    @staticmethod
    async def delete_chatbot(
        chatbot_id: UUID,
        hard: bool,
        service: ChatbotService,
    ) -> MessageResponse:
        result = await service.delete(chatbot_id, hard=hard)  # ← await
        return MessageResponse(**result)
