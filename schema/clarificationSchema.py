"""
Schema untuk Clarification Question Mechanism.
Pydantic models untuk request/response clarification flow.
"""

from typing import Optional, List, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# ================================================================ #
#  INTERNAL MODELS (tidak untuk API, untuk internal service)       #
# ================================================================ #


PRD_AMBIGUITY_TYPES = {
    "AmbiSchema",
    "AmbiValue",
    "AmbiIntent",
    "AmbiSource",
    "AmbiContext",
    "AmbiFallacy",
    "AmbiRef",
    "none",
}


class DetectedAmbiguity(BaseModel):
    """Single detected ambiguity with PRD-aligned taxonomy."""
    ambiguity_type: str
    possible_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AmbiguityAssessmentResult(BaseModel):
    """Hasil dari ambiguity detection (rule-based atau LLM-based)."""
    is_ambiguous: bool
    ambiguity_type: str  # temporal, scope, aggregation, metric, referential, none
    possible_interpretations: List[dict] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: List[str] = Field(default_factory=list)
    detection_source: str = Field(default="rules")  # rules atau llm
    detected_ambiguities: list[DetectedAmbiguity] = Field(default_factory=list)
    is_ambiguous_level1_type_llm: bool = False


class ClarificationQuestionResponse(BaseModel):
    """Single clarification question in batched response."""
    id: str
    ambiguity_type: str
    question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClarifyingQuestionData(BaseModel):
    """Data pertanyaan klarifikasi yang siap dikirim ke user."""
    clarifying_question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    default_if_no_answer: str
    ambiguity_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClarificationAnswerItem(BaseModel):
    """Single answer to a clarification question."""
    question_id: str
    selected_option: str
    free_text: Optional[str] = None


class QueryDisambiguationResult(BaseModel):
    """Hasil disambiguasi query setelah mendapat jawaban klarifikasi."""
    original_query: str
    disambiguated_query: str
    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    additional_constraints: Optional[str] = None
    clarifying_question: Optional[str] = None
    clarification_answer: Optional[str] = None
    needs_more_clarification: bool = False
    clarification_message: Optional["ClarificationMessageResponse"] = None
    preference_tree: Optional[dict[str, Any]] = None


# ================================================================ #
#  API REQUEST/RESPONSE MODELS                                    #
# ================================================================ #


class ClarificationResponseRequest(BaseModel):
    """Request untuk mengirimkan jawaban atas pertanyaan klarifikasi."""
    session_id: UUID = Field(...,
                             description="Session ID dari pertanyaan klarifikasi")

    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    additional_constraints: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "00000000-0000-0000-0000-000000000201",
            "clarification_answers": [
                {"question_id": "q1", "selected_option": "Achievement %"}
            ],
            "additional_constraints": "hanya divisi aktif",
        }
    })


class BatchedClarificationResponse(BaseModel):
    """Response with multiple clarification questions."""
    session_id: UUID
    message_type: str = Field(default="clarification")
    questions: list[ClarificationQuestionResponse]


class ClarificationMessageResponse(BaseModel):
    """Response untuk menampilkan pertanyaan klarifikasi kepada user."""
    session_id: UUID
    # "clarification" atau "direct_answer"
    message_type: str = Field(default="clarification")

    # Untuk clarification
    clarifying_question: Optional[str] = None
    options: Optional[List[str]] = None
    questions: Optional[list[ClarificationQuestionResponse]] = None

    # Untuk direct_answer dengan asumsi
    assumptions: Optional[List[str]] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "00000000-0000-0000-0000-000000000201",
            "message_type": "clarification",
            "questions": [
                {
                    "id": "q1",
                    "ambiguity_type": "AmbiSchema",
                    "question": "'Terbaik' merujuk ke metrik apa?",
                    "options": ["Achievement %", "Total realisasi", "Lewati", "Lainnya"],
                }
            ],
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
