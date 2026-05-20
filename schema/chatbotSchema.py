from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from uuid import UUID

from model.Chatbot import AuthorityEnum


# ─── Base ────────────────────────────────────────────────────────────────────

class ChatbotBase(BaseModel):
    chatbot_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        examples=["HR Assistant"],
        description="Nama unik chatbot",
    )
    authority: AuthorityEnum = Field(
        ...,
        examples=[AuthorityEnum.KEPALA_DIVISI],
        description="Otoritas akses: kepala_divisi atau Karyawan",
    )
    addon_prompt: Optional[str] = Field(
        default=None,
        description="Tambahan instruksi/prompt untuk chatbot dari FE",
    )

    @field_validator("chatbot_name")
    @classmethod
    def strip_chatbot_name(cls, v: str) -> str:
        return v.strip()


# ─── Request Schemas ──────────────────────────────────────────────────────────

class ChatbotCreate(ChatbotBase):
    """Schema untuk membuat chatbot baru."""
    pass


class ChatbotUpdate(BaseModel):
    """Schema untuk update parsial chatbot (semua field opsional)."""
    chatbot_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Nama unik chatbot",
    )
    authority: Optional[AuthorityEnum] = Field(
        default=None,
        description="Otoritas akses: Kepala Divisi atau Karyawan",
    )
    addon_prompt: Optional[str] = Field(
        default=None,
        description="Tambahan instruksi/prompt untuk chatbot dari FE",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Status aktif chatbot",
    )

    @field_validator("chatbot_name")
    @classmethod
    def strip_chatbot_name(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v else v


# ─── Response Schemas ─────────────────────────────────────────────────────────

class ChatbotResponse(ChatbotBase):
    """Schema response lengkap untuk satu chatbot."""
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatbotListResponse(BaseModel):
    """Schema response untuk list chatbot dengan pagination."""
    data: list[ChatbotResponse]
    total: int
    page: int
    limit: int
    total_pages: int


class MessageResponse(BaseModel):
    """Schema response pesan generik."""
    message: str
    success: bool = True
