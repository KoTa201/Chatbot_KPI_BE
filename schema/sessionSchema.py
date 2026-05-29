from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SessionResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SessionClarificationQuestionResponse(BaseModel):
    id: str
    ambiguity_type: str | None = None
    question: str
    options: list[str] = Field(default_factory=list)
    selected_answer: str | None = None
    free_text_answer: str | None = None
    created_at: datetime


class SessionMessageResponse(BaseModel):
    message_id: str
    message: str
    is_sender_chatbot: bool
    send_at: datetime
    clarification_questions: list[SessionClarificationQuestionResponse] = Field(default_factory=list)


class SessionDetailResponse(SessionResponse):
    messages: list[SessionMessageResponse] = Field(default_factory=list)


class UpdateSessionTitleRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("judul sesi tidak boleh kosong.")
        if len(v) > 255:
                raise ValueError("judul sesi terlalu panjang, maksimal 255 karakter.")
        return v

class SessionDeleteResponse(BaseModel):
    message: str
