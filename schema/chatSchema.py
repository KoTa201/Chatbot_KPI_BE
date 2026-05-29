from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from schema.clarificationSchema import ClarificationAnswerItem, ClarificationQuestionResponse


class ChatRequest(BaseModel):
    message: str
    session_id: UUID | None = None
    show_sql: bool = False  # Opsional: tampilkan SQL ke user
    # Jawaban atas pertanyaan klarifikasi
    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    additional_constraints: str | None = None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Pesan tidak boleh kosong.")
        if len(v) > 2000:
            raise ValueError("Pesan terlalu panjang, maksimal 2000 karakter.")
        return v


class PipelineStageInfo(BaseModel):
    stage: str
    status: str
    detail: str | None = None


class GraphicItemResponse(BaseModel):
    kpi_name: str | None = None
    chart_type: str
    image_base64: str


class ChatResponse(BaseModel):
    session_id: UUID
    message: str
    clarification_questions: list[ClarificationQuestionResponse] | None = None
    generated_sql: str | None = None
    graphics: list[GraphicItemResponse] = Field(default_factory=list)
    rows_returned: int | None = None
    execution_time_ms: int | None = None
    pipeline_stages: list[PipelineStageInfo] = Field(default_factory=list)


class ChatErrorResponse(BaseModel):
    error: str
    stage: str | None = None
    safe: bool = True
