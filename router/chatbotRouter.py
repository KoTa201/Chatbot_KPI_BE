from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, status
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from controller.chatbotController import ChatbotController
from databaseConfig import get_db
from model.Chatbot import AuthorityEnum
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
    MessageResponse,
)


class ChatbotRouter:
    """Router untuk endpoints chatbot management."""

    def __init__(self):
        self.router: APIRouter = APIRouter()
        self.chatbot_controller: ChatbotController | None = None
        self.setup_routes()

    def setup_routes(self):
        """Register all chatbot routes."""
        self.router.add_api_route(
            "/",
            self.list_chatbots,
            methods=["GET"],
            response_model=ChatbotListResponse,
            summary="Daftar semua chatbot",
            description="Get active chatbots with pagination, authority filter, and name/prompt search.",
        )
        self.router.add_api_route(
            "/{chatbot_id}",
            self.get_chatbot,
            methods=["GET"],
            response_model=ChatbotResponse,
            summary="Detail chatbot",
            description="Ambil detail satu chatbot berdasarkan ID.",
        )
        self.router.add_api_route(
            "/",
            self.create_chatbot,
            methods=["POST"],
            response_model=ChatbotResponse,
            status_code=status.HTTP_201_CREATED,
            summary="Buat chatbot baru",
            description="Create a chatbot with a unique name, authority, and optional addon prompt.",
        )
        self.router.add_api_route(
            "/{chatbot_id}",
            self.update_chatbot,
            methods=["PATCH"],
            response_model=ChatbotResponse,
            summary="Update chatbot",
            description="Update parsial chatbot — hanya kirim field yang ingin diubah.",
        )
        self.router.add_api_route(
            "/{chatbot_id}",
            self.delete_chatbot,
            methods=["DELETE"],
            response_model=MessageResponse,
            summary="Hapus chatbot",
            description=(
                "Hapus chatbot. "
                "Gunakan `?hard=true` untuk hapus permanen dari database. "
                "Default adalah soft-delete (menonaktifkan chatbot)."
            ),
        )

    async def list_chatbots(
        self,
        page: int = Query(default=1, ge=1, description="Nomor halaman"),
        limit: int = Query(default=10, ge=1, le=100,
                           description="Jumlah item per halaman"),
        authority: Optional[AuthorityEnum] = Query(
            default=None, description="Filter by authority"),
        search: Optional[str] = Query(
            default=None, description="Cari nama atau addon_prompt"),
        db: AsyncSession = Depends(get_db),
    ) -> ChatbotListResponse:
        self.chatbot_controller: ChatbotController = ChatbotController(db)
        return await self.chatbot_controller.list_chatbots(
            page=page,
            limit=limit,
            authority=authority,
            search=search,
        )

    async def get_chatbot(
        self,
        chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
        db: AsyncSession = Depends(get_db),
    ) -> ChatbotResponse:
        self.chatbot_controller: ChatbotController = ChatbotController(db)
        return await self.chatbot_controller.get_chatbot(chatbot_id=chatbot_id)

    async def create_chatbot(
        self,
        payload: ChatbotCreate,
        db: AsyncSession = Depends(get_db),
    ) -> ChatbotResponse:
        self.chatbot_controller: ChatbotController = ChatbotController(db)
        return await self.chatbot_controller.create_chatbot(payload=payload)

    async def update_chatbot(
        self,
        chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
        payload: ChatbotUpdate = ...,
        db: AsyncSession = Depends(get_db),
    ) -> ChatbotResponse:
        self.chatbot_controller: ChatbotController = ChatbotController(db)
        return await self.chatbot_controller.update_chatbot(
            chatbot_id=chatbot_id,
            payload=payload,
        )

    async def delete_chatbot(
        self,
        chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
        hard: bool = Query(
            default=False, description="True = hard delete, False = soft delete"),
        db: AsyncSession = Depends(get_db),
    ) -> MessageResponse:
        self.chatbot_controller: ChatbotController = ChatbotController(db)
        return await self.chatbot_controller.delete_chatbot(
            chatbot_id=chatbot_id,
            hard=hard,
        )


# ─── Router instance ─────────────────────────────────────────────────────
router = ChatbotRouter().router
