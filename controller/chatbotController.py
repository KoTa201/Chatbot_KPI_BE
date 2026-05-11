from typing import Optional
from uuid import UUID
from fastapi import Depends, HTTPException, status
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
        limit: int,
        otoritas: Optional[AuthorityEnum],
        search: Optional[str],
    ) -> ChatbotListResponse:
        if limit < 1 or limit > 100:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'limit' harus antara 1 dan 100.",
            )
        if page < 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="'page' tidak boleh negatif dan minimal 1.",
            )
        chatbots = await self.service.get_all(page, limit, otoritas, search)

        return ChatbotListResponse(
            data=chatbots["data"],
            total=chatbots["total"],
            page=chatbots["page"],
            limit=chatbots["limit"],
            total_pages=chatbots["total_pages"],
        )

    async def get_chatbot(self, chatbot_id: UUID) -> ChatbotResponse:
        chatbot = await self.service.get_by_id(chatbot_id)
        return ChatbotResponse.model_validate(chatbot)

    async def create_chatbot(self, payload: ChatbotCreate) -> ChatbotResponse:
        chatbot = await self.service.create(payload)
        return ChatbotResponse.model_validate(chatbot)

    async def update_chatbot(
        self,
        chatbot_id: UUID,
        payload: ChatbotUpdate,
    ) -> ChatbotResponse:
        chatbot = await self.service.update(chatbot_id, payload)
        return ChatbotResponse.model_validate(chatbot)

    async def delete_chatbot(
        self,
        chatbot_id: UUID,
        hard: bool,
    ) -> MessageResponse:
        result = await self.service.delete(chatbot_id, hard=hard)
        return MessageResponse(**result)
