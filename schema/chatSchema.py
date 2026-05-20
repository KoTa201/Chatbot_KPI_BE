from typing import Optional, List
from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    show_sql: bool = False  # Opsional: tampilkan SQL ke user
    # Jawaban atas pertanyaan klarifikasi
    clarification_answer: Optional[str] = None

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


class ChatResponse(BaseModel):
    session_id: str
    message: str                        # Jawaban naratif dari LLM
    # Jika ada pertanyaan klarifikasi
    clarification_message_answer_options: List[str] | None = None
    generated_sql: str | None = None    # Hanya ditampilkan jika show_sql=True
    graphic_chart_type: str | None = None
    graphic_image_base64: str | None = None
    rows_returned: int | None = None
    execution_time_ms: int | None = None
    pipeline_stages: list[PipelineStageInfo] = []


class ChatErrorResponse(BaseModel):
    error: str
    stage: str | None = None
    safe: bool = True
