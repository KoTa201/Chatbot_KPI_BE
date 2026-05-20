"""
Schema untuk Clarification Question Mechanism.
Pydantic models untuk request/response clarification flow.
"""

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# ================================================================ #
#  INTERNAL MODELS (tidak untuk API, untuk internal service)       #
# ================================================================ #


class AmbiguityAssessmentResult(BaseModel):
    """Hasil dari ambiguity detection (rule-based atau LLM-based)."""
    ambiguity_score: float = Field(..., ge=0.0, le=1.0)
    is_ambiguous: bool
    ambiguity_type: str  # temporal, scope, aggregation, metric, referential, none
    possible_interpretations: List[dict] = Field(default_factory=list)
    suggested_clarifying_question: Optional[str] = None
    answer_options: List[str] = Field(default_factory=list)
    detection_source: str = Field(default="rules")  # rules atau llm


class ClarifyingQuestionData(BaseModel):
    """Data pertanyaan klarifikasi yang siap dikirim ke user."""
    clarifying_question: str
    options: List[str] = Field(..., min_length=2, max_length=4)
    default_if_no_answer: str
    ambiguity_type: str


class QueryDisambiguationResult(BaseModel):
    """Hasil disambiguasi query setelah mendapat jawaban klarifikasi."""
    original_query: str
    clarifying_question: str
    clarification_answer: str
    disambiguated_query: str


# ================================================================ #
#  API REQUEST/RESPONSE MODELS                                    #
# ================================================================ #


class ClarificationResponseRequest(BaseModel):
    """Request untuk mengirimkan jawaban atas pertanyaan klarifikasi."""
    session_id: UUID = Field(...,
                             description="Session ID dari pertanyaan klarifikasi")
    answer: str = Field(...,
                        description="Jawaban pengguna (pilihan chip atau teks bebas)")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_123",
            "answer": "Per divisi"
        }
    })


class ClarificationMessageResponse(BaseModel):
    """Response untuk menampilkan pertanyaan klarifikasi kepada user."""
    session_id: UUID
    # "clarification" atau "direct_answer"
    message_type: str = Field(default="clarification")

    # Untuk clarification
    clarifying_question: Optional[str] = None
    options: Optional[List[str]] = None

    # Untuk direct_answer dengan asumsi
    assumptions: Optional[List[str]] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_123",
            "message_type": "clarification",
            "clarifying_question": "Apakah Anda ingin melihat performa per individu, per divisi, atau keseluruhan?",
            "options": ["Per individu karyawan", "Per divisi", "Keseluruhan perusahaan"]
        }
    })


# ================================================================ #
#  LOGGING MODELS (untuk audit/tracking)                          #
# ================================================================ #


class ClarificationLogEntry(BaseModel):
    """Entry untuk logging clarification mechanism."""
    id: Optional[UUID] = None
    session_id: UUID
    user_id: UUID
    user_role: str
    original_query: str
    ambiguity_score: float
    ambiguity_type: str
    decision: str  # "clarify" atau "direct"
    decision_source: str  # "rules" atau "llm"
    clarifying_question: Optional[str] = None
    clarification_answer: Optional[str] = None
    disambiguated_query: Optional[str] = None
    user_feedback: Optional[bool] = None  # true=relevan, false=tidak relevan
    needed_correction: Optional[bool] = None  # apakah pengguna bertanya ulang?
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ================================================================ #
#  SESSION CONTEXT MODELS                                         #
# ================================================================ #


class SessionClarificationContext(BaseModel):
    """Context clarification disimpan per session."""
    session_id: UUID
    clarification_history: List[dict] = Field(default_factory=list)
    # menyimpan preferensi yang sudah dijawab
    scope_preferences: dict = Field(default_factory=dict)
    clarification_count: int = 0
    last_clarification_at: Optional[datetime] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_123",
            "clarification_history": [
                {
                    "question": "Per individu atau per divisi?",
                    "answer": "Per divisi",
                    "timestamp": "2025-04-18T10:30:00Z"
                }
            ],
            "scope_preferences": {
                "scope": "divisi",
                "period": "2025"
            },
            "clarification_count": 1
        }
    })
