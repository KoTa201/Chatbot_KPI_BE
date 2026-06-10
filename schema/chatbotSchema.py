from pydantic import BaseModel, Field, field_validator, AliasChoices
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
        validation_alias=AliasChoices("chatbot_name", "nama_chatbot"),
        serialization_alias="nama_chatbot",
    )
    authority: AuthorityEnum = Field(
        ...,
        examples=[AuthorityEnum.KEPALA_DIVISI],
        description="Otoritas akses: kepala_divisi atau Karyawan",
        validation_alias=AliasChoices("authority", "otoritas"),
        serialization_alias="otoritas",
    )
    addon_prompt: Optional[str] = Field(
        default=None,
        description="Tambahan instruksi/prompt untuk chatbot dari FE",
    )

    model_config = {
        "populate_by_name": True,
    }

    @field_validator("chatbot_name")
    @classmethod
    def strip_chatbot_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("chatbot_name tidak boleh kosong")
        return stripped


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
        validation_alias=AliasChoices("chatbot_name", "nama_chatbot"),
        serialization_alias="nama_chatbot",
    )
    authority: Optional[AuthorityEnum] = Field(
        default=None,
        description="Otoritas akses: Kepala Divisi atau Karyawan",
        validation_alias=AliasChoices("authority", "otoritas"),
        serialization_alias="otoritas",
    )
    addon_prompt: Optional[str] = Field(
        default=None,
        description="Tambahan instruksi/prompt untuk chatbot dari FE",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Status aktif chatbot",
    )

    model_config = {
        "populate_by_name": True,
    }

    @field_validator("chatbot_name")
    @classmethod
    def strip_chatbot_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("chatbot_name tidak boleh kosong")
        return stripped


# ─── Response Schemas ─────────────────────────────────────────────────────────

class ChatbotResponse(ChatbotBase):
    """Schema response lengkap untuk satu chatbot."""
    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class ChatbotListResponse(BaseModel):
    """Schema response untuk list chatbot dengan pagination."""
    data: list[ChatbotResponse]
    total: int
    page: int
    limit: int = Field(
        ..., validation_alias=AliasChoices("limit", "page_size"), serialization_alias="page_size"
    )
    total_pages: int

    model_config = {
        "populate_by_name": True,
    }


class MessageResponse(BaseModel):
    """Schema response pesan generik."""
    message: str
    success: bool = True
