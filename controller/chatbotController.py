from typing import Optional
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from model.Chatbot import AuthorityEnum
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
    MessageResponse,
)
from exceptions import translate_app_errors
from service.chatbotService import ChatbotService
from utils.pagination import validate_limit, validate_page


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
        authority: Optional[AuthorityEnum],
        search: Optional[str],
    ) -> ChatbotListResponse:
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
        chatbots = await self.service.get_all(page, limit, authority, search)

        return ChatbotListResponse(
            data=chatbots["data"],
            total=chatbots["total"],
            page=chatbots["page"],
            limit=chatbots["limit"],
            total_pages=chatbots["total_pages"],
        )

    @translate_app_errors
    async def get_chatbot(self, chatbot_id: UUID) -> ChatbotResponse:
        chatbot = await self.service.get_by_id(chatbot_id)
        return ChatbotResponse.model_validate(chatbot)

    @translate_app_errors
    async def create_chatbot(self, payload: ChatbotCreate) -> ChatbotResponse:
        chatbot = await self.service.create(payload)
        return ChatbotResponse.model_validate(chatbot)

    @translate_app_errors
    async def update_chatbot(
        self,
        chatbot_id: UUID,
        payload: ChatbotUpdate,
    ) -> ChatbotResponse:
        chatbot = await self.service.update(chatbot_id, payload)
        return ChatbotResponse.model_validate(chatbot)

    @translate_app_errors
    async def delete_chatbot(
        self,
        chatbot_id: UUID,
        hard: bool,
    ) -> MessageResponse:
        result = await self.service.delete(chatbot_id, hard=hard)
        return MessageResponse(**result)
