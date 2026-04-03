from typing import Optional
from fastapi import APIRouter, Depends, Query, Path, status
from uuid import UUID

from controller.chatbotController import ChatbotController, get_chatbot_service
from model.Chatbot import AuthorityEnum
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
    MessageResponse,
)
from service.chatbotService import ChatbotService

router = APIRouter()


@router.get(
    "/",
    response_model=ChatbotListResponse,
    summary="Daftar semua chatbot",
    description="Ambil seluruh chatbot aktif dengan pagination, filter otoritas, dan pencarian nama/prompt.",
)
async def list_chatbots(
    page: int = Query(default=1, ge=1, description="Nomor halaman"),
    page_size: int = Query(default=10, ge=1, le=100,
                           description="Jumlah item per halaman"),
    otoritas: Optional[AuthorityEnum] = Query(
        default=None, description="Filter berdasarkan otoritas"),
    search: Optional[str] = Query(
        default=None, description="Cari nama atau addon_prompt"),
    service: ChatbotService = Depends(get_chatbot_service),
) -> ChatbotListResponse:
    return await ChatbotController.list_chatbots(
        page=page,
        page_size=page_size,
        otoritas=otoritas,
        search=search,
        service=service,
    )


@router.get(
    "/{chatbot_id}",
    response_model=ChatbotResponse,
    summary="Detail chatbot",
    description="Ambil detail satu chatbot berdasarkan ID.",
)
async def get_chatbot(
    chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
    service: ChatbotService = Depends(get_chatbot_service),
) -> ChatbotResponse:
    return await ChatbotController.get_chatbot(chatbot_id=chatbot_id, service=service)


@router.post(
    "/",
    response_model=ChatbotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Buat chatbot baru",
    description="Tambah chatbot baru dengan nama unik, otoritas, dan addon prompt opsional.",
)
async def create_chatbot(
    payload: ChatbotCreate,
    service: ChatbotService = Depends(get_chatbot_service),
) -> ChatbotResponse:
    return await ChatbotController.create_chatbot(payload=payload, service=service)


@router.patch(
    "/{chatbot_id}",
    response_model=ChatbotResponse,
    summary="Update chatbot",
    description="Update parsial chatbot — hanya kirim field yang ingin diubah.",
)
async def update_chatbot(
    chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
    payload: ChatbotUpdate = ...,
    service: ChatbotService = Depends(get_chatbot_service),
) -> ChatbotResponse:
    return await ChatbotController.update_chatbot(
        chatbot_id=chatbot_id,
        payload=payload,
        service=service,
    )


@router.delete(
    "/{chatbot_id}",
    response_model=MessageResponse,
    summary="Hapus chatbot",
    description=(
        "Hapus chatbot. "
        "Gunakan `?hard=true` untuk hapus permanen dari database. "
        "Default adalah soft-delete (menonaktifkan chatbot)."
    ),
)
async def delete_chatbot(
    chatbot_id: UUID = Path(..., description="ID chatbot (UUID)"),
    hard: bool = Query(
        default=False, description="True = hard delete, False = soft delete"),
    service: ChatbotService = Depends(get_chatbot_service),
) -> MessageResponse:
    return await ChatbotController.delete_chatbot(
        chatbot_id=chatbot_id,
        hard=hard,
        service=service,
    )
