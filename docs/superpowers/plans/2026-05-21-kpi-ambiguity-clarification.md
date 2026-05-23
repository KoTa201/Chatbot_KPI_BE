# KPI Ambiguity Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build PRD-aligned batched ambiguity detection and clarification for KPI Text-to-SQL queries.

**Architecture:** Keep the ambiguity mechanism LLM-based, but make it multi-item and grounded in compact KPI schema/sample context. Stage 0 in `ChatService` returns a batch of clarification questions when needed; `/chat/clarification` accepts a batch of answers, rewrites the query once, and resumes the existing NL-to-SQL pipeline.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async ORM, Alembic, pytest, pytest-asyncio, OpenAI-compatible LLM wrapper.

---

## File structure

- Modify `schema/clarificationSchema.py`: add multi-ambiguity, batched question, batched answer, and rewrite result schemas.
- Modify `schema/chatSchema.py`: add `clarification_questions`, `clarification_answers`, and `additional_constraints` to chat request/response shapes.
- Create `service/kpiAmbiguityContextService.py`: compact KPI domain context builder for LLM prompts.
- Modify `template/promptTemplate.py`: replace single-ambiguity prompt with AmbiSQL/KPI taxonomy prompt; add batched rewrite prompt.
- Modify `service/ambiguityDetectorService.py`: parse multi-ambiguity JSON arrays and preserve safe fallback.
- Modify `service/clarificationQuestionGeneratorService.py`: normalize one question per ambiguity and enforce `Lewati`/`Lainnya` options.
- Modify `model/ClarificationQuestion.py`: store selected answer/free text and optional session ID for session-aware lookup.
- Modify `alembic/versions/6fac3aac3721_replace_chat_schema.py`: align replacement migration with new clarification question columns.
- Modify `repository/clarificationRepository.py`: create/list/update batched questions with session filtering.
- Modify `service/clarificationService.py`: orchestrate batched detection/questioning and batched answer rewriting.
- Modify `controller/chatController.py`: validate batched clarification answers.
- Modify `service/chatService.py`: return batched clarification questions in Stage 0 and skip detection for rewritten query continuation.
- Modify tests in `tests/clarificationMechanism_test.py`, `tests/chatPipeline_test.py`, and `tests/chatStreaming_test.py` as needed.

---

### Task 1: Add batched clarification schemas

**Files:**
- Modify: `schema/clarificationSchema.py`
- Modify: `schema/chatSchema.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing schema tests**

Append these tests to `tests/clarificationMechanism_test.py` near the existing schema-related imports. If imports are missing, add `from schema.clarificationSchema import DetectedAmbiguity, BatchedClarificationResponse, ClarificationAnswerItem`.

```python
def test_detected_ambiguity_schema_accepts_prd_taxonomy():
    ambiguity = DetectedAmbiguity(
        ambiguous_phrase="terbaik",
        ambiguity_type="AmbiSchema",
        ambiguity_score=0.91,
        possible_interpretations=[{"interpretation": "achievement percentage"}],
        suggested_clarifying_question="'Terbaik' merujuk ke metrik apa?",
        answer_options=["Achievement %", "Total realisasi"],
        metadata={"candidate_columns": ["achievement_percentage", "realization"]},
    )

    assert ambiguity.ambiguity_type == "AmbiSchema"
    assert ambiguity.metadata["candidate_columns"] == ["achievement_percentage", "realization"]


def test_batched_clarification_response_schema():
    response = BatchedClarificationResponse(
        session_id=SESSION_TEST_1,
        questions=[
            {
                "id": "q1",
                "ambiguous_phrase": "terbaik",
                "ambiguity_type": "AmbiSchema",
                "question": "'Terbaik' merujuk ke metrik apa?",
                "options": ["Achievement %", "Total realisasi", "Lewati", "Lainnya"],
                "metadata": {"source": "llm"},
            }
        ],
    )

    assert response.message_type == "clarification"
    assert response.questions[0].options[-2:] == ["Lewati", "Lainnya"]


def test_clarification_answer_item_uses_free_text_for_lainnya():
    answer = ClarificationAnswerItem(
        question_id="q1",
        selected_option="Lainnya",
        free_text="Gunakan weighted achievement score",
    )

    assert answer.question_id == "q1"
    assert answer.free_text == "Gunakan weighted achievement score"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_detected_ambiguity_schema_accepts_prd_taxonomy tests/clarificationMechanism_test.py::test_batched_clarification_response_schema tests/clarificationMechanism_test.py::test_clarification_answer_item_uses_free_text_for_lainnya -v
```

Expected: FAIL with import errors for `DetectedAmbiguity`, `BatchedClarificationResponse`, or `ClarificationAnswerItem`.

- [ ] **Step 3: Implement schemas in `schema/clarificationSchema.py`**

Replace the internal model section with these models while keeping existing public names that other tests still import:

```python
from typing import Any, Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

PRD_AMBIGUITY_TYPES = {
    "AmbiSchema",
    "AmbiValue",
    "AmbiIntent",
    "AmbiContext",
    "AmbiFallacy",
    "AmbiRef",
    "none",
}


class DetectedAmbiguity(BaseModel):
    ambiguous_phrase: str | None = None
    ambiguity_type: str
    ambiguity_score: float = Field(..., ge=0.0, le=1.0)
    possible_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AmbiguityAssessmentResult(BaseModel):
    ambiguity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    is_ambiguous: bool
    ambiguity_type: str = "none"
    possible_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    detection_source: str = Field(default="llm")
    detected_ambiguities: list[DetectedAmbiguity] = Field(default_factory=list)


class ClarificationQuestionResponse(BaseModel):
    id: str
    ambiguous_phrase: str | None = None
    ambiguity_type: str
    question: str
    options: list[str] = Field(..., min_length=2, max_length=7)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClarifyingQuestionData(BaseModel):
    clarifying_question: str
    options: list[str] = Field(..., min_length=2, max_length=7)
    default_if_no_answer: str
    ambiguity_type: str
    ambiguous_phrase: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchedClarificationResponse(BaseModel):
    session_id: UUID
    message_type: str = Field(default="clarification")
    questions: list[ClarificationQuestionResponse]


class ClarificationAnswerItem(BaseModel):
    question_id: str
    selected_option: str
    free_text: str | None = None


class QueryDisambiguationResult(BaseModel):
    original_query: str
    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    disambiguated_query: str
    additional_constraints: str | None = None


class ClarificationResponseRequest(BaseModel):
    session_id: UUID = Field(..., description="Session ID dari pertanyaan klarifikasi")
    answer: str | None = Field(default=None, description="Legacy single answer")
    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    additional_constraints: str | None = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "00000000-0000-0000-0000-000000000201",
            "clarification_answers": [
                {"question_id": "q1", "selected_option": "Achievement %"}
            ],
            "additional_constraints": "hanya divisi aktif",
        }
    })


class ClarificationMessageResponse(BaseModel):
    session_id: UUID
    message_type: str = Field(default="clarification")
    clarifying_question: Optional[str] = None
    options: Optional[List[str]] = None
    questions: list[ClarificationQuestionResponse] | None = None
    assumptions: Optional[List[str]] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "00000000-0000-0000-0000-000000000201",
            "message_type": "clarification",
            "questions": [
                {
                    "id": "q1",
                    "ambiguous_phrase": "terbaik",
                    "ambiguity_type": "AmbiSchema",
                    "question": "'Terbaik' merujuk ke metrik apa?",
                    "options": ["Achievement %", "Total realisasi", "Lewati", "Lainnya"],
                }
            ],
        }
    })
```

Keep the existing `ClarificationLogEntry` and `SessionClarificationContext` classes below this block, updating their type imports to use `Any` if needed.

- [ ] **Step 4: Update `schema/chatSchema.py`**

Modify imports and models:

```python
from typing import Any, Optional, List
from uuid import UUID

from pydantic import BaseModel, field_validator

from schema.clarificationSchema import ClarificationAnswerItem, ClarificationQuestionResponse
```

Add fields to `ChatRequest`:

```python
    clarification_answers: list[ClarificationAnswerItem] = []
    additional_constraints: str | None = None
```

Add field to `ChatResponse`:

```python
    clarification_questions: list[ClarificationQuestionResponse] | None = None
```

Keep `clarification_message_answer_options` temporarily for compatibility with current tests/clients.

- [ ] **Step 5: Run schema tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_detected_ambiguity_schema_accepts_prd_taxonomy tests/clarificationMechanism_test.py::test_batched_clarification_response_schema tests/clarificationMechanism_test.py::test_clarification_answer_item_uses_free_text_for_lainnya -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add schema/clarificationSchema.py schema/chatSchema.py tests/clarificationMechanism_test.py
git commit -m "feat: add batched clarification schemas"
```

---

### Task 2: Add KPI ambiguity context builder

**Files:**
- Create: `service/kpiAmbiguityContextService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing context builder tests**

Append:

```python
from service.kpiAmbiguityContextService import KPIAmbiguityContextService


def test_kpi_ambiguity_context_contains_domain_terms():
    context = KPIAmbiguityContextService().build_context()

    assert "KPI Master" in context
    assert "KPI Tracker" in context
    assert "target" in context.lower()
    assert "realisasi" in context.lower()
    assert "achievement" in context.lower()


def test_kpi_ambiguity_context_is_bounded():
    context = KPIAmbiguityContextService().build_context()

    assert len(context) < 4000
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_kpi_ambiguity_context_contains_domain_terms tests/clarificationMechanism_test.py::test_kpi_ambiguity_context_is_bounded -v
```

Expected: FAIL because `service.kpiAmbiguityContextService` does not exist.

- [ ] **Step 3: Create `service/kpiAmbiguityContextService.py`**

```python
class KPIAmbiguityContextService:
    def build_context(self) -> str:
        return """
Domain KPI chatbot:
- KPI Master: definisi KPI, aktivitas, kategori, target, satuan, dan operational definition.
- KPI Tracker: realisasi KPI per bulan/tahun, status pencapaian, nilai aktual, dan persentase achievement.
- Dimensi organisasi: karyawan, kepala divisi, divisi/departemen, dan cakupan seluruh organisasi.
- Dimensi waktu: bulan, tahun, kuartal, tahun berjalan, tahun lalu, bulan ini, dan bulan terakhir data.
- Metrik umum: target, realisasi, achievement percentage, performance score, jumlah KPI, total, rata-rata.
- Status umum: achieved, partial, failed, tercapai, belum tercapai.
AmbiSchema candidates: kata seperti terbaik/performa/nilai dapat merujuk ke achievement percentage, realisasi, target, atau score.
AmbiValue candidates: nama divisi, nama KPI, kategori KPI, nama karyawan, periode, dan status harus cocok dengan nilai data aktual bila tersedia.
AmbiIntent candidates: tampilkan dapat berarti list, ranking, filter, grouping, comparison, atau aggregation.
""".strip()
```

- [ ] **Step 4: Run context tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_kpi_ambiguity_context_contains_domain_terms tests/clarificationMechanism_test.py::test_kpi_ambiguity_context_is_bounded -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/kpiAmbiguityContextService.py tests/clarificationMechanism_test.py
git commit -m "feat: add KPI ambiguity context builder"
```

---

### Task 3: Update prompts for AmbiSQL taxonomy and batched rewrite

**Files:**
- Modify: `template/promptTemplate.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing prompt tests**

Append:

```python
from template.promptTemplate import build_ambiguity_assessment_prompt, build_query_disambiguation_prompt
from schema.clarificationSchema import ClarificationAnswerItem


def test_ambiguity_prompt_uses_prd_taxonomy_and_context():
    prompt = build_ambiguity_assessment_prompt(
        user_query="Tampilkan sales terbaik tahun lalu",
        user_role="Kepala Divisi",
        kpi_context="KPI Master dan KPI Tracker context",
    )

    assert "AmbiSchema" in prompt
    assert "AmbiValue" in prompt
    assert "AmbiIntent" in prompt
    assert "AmbiRef" in prompt
    assert "detected_ambiguities" in prompt
    assert "KPI Master dan KPI Tracker context" in prompt


def test_query_disambiguation_prompt_supports_batched_answers():
    prompt = build_query_disambiguation_prompt(
        original_query="Tampilkan sales terbaik tahun lalu",
        clarification_answers=[
            ClarificationAnswerItem(question_id="q1", selected_option="Achievement %"),
            ClarificationAnswerItem(question_id="q2", selected_option="Calendar Year 2025"),
        ],
        additional_constraints="hanya divisi aktif",
    )

    assert "Achievement %" in prompt
    assert "Calendar Year 2025" in prompt
    assert "hanya divisi aktif" in prompt
```

- [ ] **Step 2: Run prompt tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_ambiguity_prompt_uses_prd_taxonomy_and_context tests/clarificationMechanism_test.py::test_query_disambiguation_prompt_supports_batched_answers -v
```

Expected: FAIL because signatures/content still use old prompt shape.

- [ ] **Step 3: Replace `build_ambiguity_assessment_prompt` signature and body**

In `template/promptTemplate.py`, change function signature:

```python
def build_ambiguity_assessment_prompt(
    user_query: str,
    user_role: str,
    kpi_context: str = "",
) -> str:
```

Use this body:

```python
    prompt = f"""[SYSTEM PROMPT — KPI AMBISQL AMBIGUITY ASSESSOR]
Kamu adalah sistem deteksi ambiguitas untuk chatbot KPI Text-to-SQL.
Tugasmu: identifikasi SEMUA frasa ambigu yang dapat mengubah SQL atau hasil KPI secara material.

Konteks domain KPI:
{kpi_context}

Role pengguna saat ini: {user_role}
Pertanyaan pengguna: "{user_query}"

Gunakan taksonomi berikut:
- AmbiSchema: frasa dapat merujuk ke lebih dari satu tabel/kolom/metrik KPI, misalnya terbaik = achievement %, realisasi, target, atau score.
- AmbiValue: nilai user tidak jelas atau mungkin tidak cocok dengan nilai aktual, misalnya nama divisi, KPI, karyawan, status, periode.
- AmbiIntent: operasi bisnis tidak jelas, misalnya tampilkan sebagai daftar, ranking, grouping, filter, perbandingan, total, atau rata-rata.
- AmbiContext: konteks bisnis kurang, misalnya cakupan aktif/nonaktif, mata uang, organisasi, atau aturan KPI.
- AmbiFallacy: asumsi user mungkin bertentangan dengan data yang tersedia.
- AmbiRef: referensi temporal/spasial tidak spesifik, misalnya bulan ini, tahun lalu, Q3, awal tahun, setelah target tercapai.

Aturan:
- Return maksimal 5 detected_ambiguities, urutkan dari paling berdampak ke SQL.
- Gunakan Bahasa Indonesia bisnis, bukan istilah SQL, untuk pertanyaan klarifikasi.
- answer_options harus 2 sampai 5 opsi sebelum opsi default Lewati/Lainnya ditambahkan sistem.
- Jika tidak ambigu, return detected_ambiguities kosong dan is_ambiguous false.
- Borderline atau dampak rendah lebih baik tidak ditanya.

Jawab HANYA JSON valid:
{{
  "is_ambiguous": <boolean>,
  "ambiguity_score": <float 0.0-1.0>,
  "detected_ambiguities": [
    {{
      "ambiguous_phrase": <string>,
      "ambiguity_type": "AmbiSchema" | "AmbiValue" | "AmbiIntent" | "AmbiContext" | "AmbiFallacy" | "AmbiRef",
      "ambiguity_score": <float 0.0-1.0>,
      "possible_interpretations": [{{"interpretation": <string>, "kpi_impact": <string>}}],
      "suggested_clarifying_question": <string>,
      "answer_options": [<string>],
      "metadata": {{}}
    }}
  ]
}}"""

    return prompt
```

- [ ] **Step 4: Replace `build_query_disambiguation_prompt` signature and body**

Change signature:

```python
def build_query_disambiguation_prompt(
    original_query: str,
    clarification_answers: list,
    additional_constraints: str | None = None,
) -> str:
```

Use this body:

```python
    answer_lines = []
    for answer in clarification_answers:
        selected = getattr(answer, "selected_option", None) or answer.get("selected_option")
        free_text = getattr(answer, "free_text", None) if not isinstance(answer, dict) else answer.get("free_text")
        question_id = getattr(answer, "question_id", None) or answer.get("question_id")
        effective_answer = free_text if selected == "Lainnya" and free_text else selected
        answer_lines.append(f"- {question_id}: {effective_answer}")

    constraints = additional_constraints or "Tidak ada constraint tambahan."

    prompt = f"""[SYSTEM PROMPT — KPI QUERY DISAMBIGUATOR]
Pengguna awalnya bertanya: "{original_query}"

Jawaban klarifikasi:
{chr(10).join(answer_lines)}

Constraint tambahan:
{constraints}

Tulis ulang pertanyaan pengguna menjadi satu query Bahasa Indonesia yang eksplisit untuk Text-to-SQL KPI.
Aturan:
- Masukkan semua jawaban kecuali yang bernilai Lewati.
- Jika ada Lewati, jangan mengarang nilai; biarkan aspek tersebut tidak dispesifikkan.
- Jika ada Lainnya, gunakan free_text sebagai klarifikasi utama.
- Prioritaskan constraint tambahan dari user.
- Jangan output JSON atau penjelasan.

Query hasil disambiguasi:"""

    return prompt
```

- [ ] **Step 5: Run prompt tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_ambiguity_prompt_uses_prd_taxonomy_and_context tests/clarificationMechanism_test.py::test_query_disambiguation_prompt_supports_batched_answers -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add template/promptTemplate.py tests/clarificationMechanism_test.py
git commit -m "feat: update KPI ambiguity prompts"
```

---

### Task 4: Parse multi-ambiguity detector output

**Files:**
- Modify: `service/ambiguityDetectorService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing detector tests**

Append:

```python
@pytest.mark.asyncio
async def test_llm_detects_multiple_prd_ambiguities():
    detector = AmbiguityDetectorService()

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '''{
            "is_ambiguous": true,
            "ambiguity_score": 0.91,
            "detected_ambiguities": [
                {
                    "ambiguous_phrase": "terbaik",
                    "ambiguity_type": "AmbiSchema",
                    "ambiguity_score": 0.92,
                    "possible_interpretations": [{"interpretation": "achievement percentage"}],
                    "suggested_clarifying_question": "'Terbaik' merujuk ke metrik apa?",
                    "answer_options": ["Achievement %", "Total realisasi"],
                    "metadata": {"candidate_columns": ["achievement_percentage", "realization"]}
                },
                {
                    "ambiguous_phrase": "tahun lalu",
                    "ambiguity_type": "AmbiRef",
                    "ambiguity_score": 0.88,
                    "possible_interpretations": [{"interpretation": "calendar year"}],
                    "suggested_clarifying_question": "'Tahun lalu' merujuk ke periode mana?",
                    "answer_options": ["Calendar Year 2025", "Fiscal Year 2025"],
                    "metadata": {}
                }
            ]
        }'''

        result = await detector.detect_ambiguity(
            "Tampilkan sales terbaik tahun lalu",
            "Kepala Divisi",
            "KPI context",
        )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "AmbiSchema"
    assert len(result.detected_ambiguities) == 2
    assert result.detected_ambiguities[1].ambiguity_type == "AmbiRef"
```

- [ ] **Step 2: Run detector test to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_llm_detects_multiple_prd_ambiguities -v
```

Expected: FAIL because `detect_ambiguity` does not accept `kpi_context` or populate `detected_ambiguities`.

- [ ] **Step 3: Update detector imports**

In `service/ambiguityDetectorService.py`, change schema import:

```python
from schema.clarificationSchema import AmbiguityAssessmentResult, DetectedAmbiguity
```

- [ ] **Step 4: Update detector method signatures**

Change signatures:

```python
async def detect_ambiguity(
    self, user_query: str, user_role: str, kpi_context: str = ""
) -> AmbiguityAssessmentResult:
```

```python
async def _assess_ambiguity_with_llm(
    self, user_query: str, user_role: str, kpi_context: str = ""
) -> AmbiguityAssessmentResult:
```

Call internal method with `kpi_context`.

- [ ] **Step 5: Update prompt call and parsing**

In `_assess_ambiguity_with_llm`, call:

```python
prompt = build_ambiguity_assessment_prompt(user_query, user_role, kpi_context)
```

After `result_dict = self._parse_llm_json_response(response)`, parse:

```python
detected_items = result_dict.get("detected_ambiguities", []) or []
detected_ambiguities = [
    DetectedAmbiguity(
        ambiguous_phrase=item.get("ambiguous_phrase"),
        ambiguity_type=item.get("ambiguity_type", "none"),
        ambiguity_score=float(item.get("ambiguity_score", result_dict.get("ambiguity_score", 0.0))),
        possible_interpretations=item.get("possible_interpretations", []) or [],
        suggested_clarifying_question=item.get("suggested_clarifying_question"),
        answer_options=item.get("answer_options") or item.get("suggested_options", []) or [],
        metadata=item.get("metadata", {}) or {},
    )
    for item in detected_items
    if isinstance(item, dict)
]

ambiguity_score = float(result_dict.get("ambiguity_score", 0.0))
is_ambiguous = bool(detected_ambiguities) and ambiguity_score >= self.AMBIGUITY_THRESHOLD
primary = detected_ambiguities[0] if detected_ambiguities else None

return AmbiguityAssessmentResult(
    ambiguity_score=ambiguity_score,
    is_ambiguous=is_ambiguous,
    ambiguity_type=primary.ambiguity_type if primary else result_dict.get("ambiguity_type", "none"),
    possible_interpretations=primary.possible_interpretations if primary else result_dict.get("possible_interpretations", []) or [],
    suggested_clarifying_question=primary.suggested_clarifying_question if primary else result_dict.get("suggested_clarifying_question"),
    answer_options=primary.answer_options if primary else result_dict.get("answer_options", []) or [],
    detection_source="llm",
    detected_ambiguities=detected_ambiguities,
)
```

Keep existing fenced JSON parsing and fallback behavior. In fallback result, add `detected_ambiguities=[]`.

- [ ] **Step 6: Run detector tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_llm_detects_multiple_prd_ambiguities tests/clarificationMechanism_test.py::test_llm_json_in_markdown_fence tests/clarificationMechanism_test.py::test_llm_api_error_fallback -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service/ambiguityDetectorService.py tests/clarificationMechanism_test.py
git commit -m "feat: parse batched KPI ambiguities"
```

---

### Task 5: Normalize clarification question options

**Files:**
- Modify: `service/clarificationQuestionGeneratorService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing option normalization tests**

Append:

```python
@pytest.mark.asyncio
async def test_question_generator_appends_skip_and_other_to_suggested_options():
    generator = ClarificationQuestionGeneratorService()

    result = await generator.generate_clarifying_question(
        user_query="Tampilkan sales terbaik",
        ambiguity_type="AmbiSchema",
        possible_interpretations=[],
        suggested_question="'Terbaik' merujuk ke metrik apa?",
        suggested_options=["Achievement %", "Total realisasi"],
        user_role="Kepala Divisi",
        ambiguous_phrase="terbaik",
        metadata={"candidate_columns": ["achievement_percentage"]},
    )

    assert result.options == ["Achievement %", "Total realisasi", "Lewati", "Lainnya"]
    assert result.ambiguous_phrase == "terbaik"
    assert result.metadata["candidate_columns"] == ["achievement_percentage"]


@pytest.mark.asyncio
async def test_question_generator_limits_options_before_defaults():
    generator = ClarificationQuestionGeneratorService()

    result = await generator.generate_clarifying_question(
        user_query="Tampilkan performa",
        ambiguity_type="AmbiSchema",
        possible_interpretations=[],
        suggested_question="Metrik performa mana?",
        suggested_options=["A", "B", "C", "D", "E", "F"],
        user_role="Admin",
    )

    assert result.options == ["A", "B", "C", "D", "E", "Lewati", "Lainnya"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_question_generator_appends_skip_and_other_to_suggested_options tests/clarificationMechanism_test.py::test_question_generator_limits_options_before_defaults -v
```

Expected: FAIL because method signature/options do not support metadata/default options.

- [ ] **Step 3: Update method signature**

In `service/clarificationQuestionGeneratorService.py`, change `generate_clarifying_question` signature:

```python
async def generate_clarifying_question(
    self,
    user_query: str,
    ambiguity_type: str,
    possible_interpretations: list[dict],
    suggested_question: Optional[str],
    suggested_options: Optional[list[str]],
    user_role: str,
    ambiguous_phrase: str | None = None,
    metadata: dict | None = None,
) -> ClarifyingQuestionData:
```

- [ ] **Step 4: Add normalizer helper**

Inside class:

```python
    @staticmethod
    def _normalize_options(options: list[str]) -> list[str]:
        normalized: list[str] = []
        for option in options:
            text = str(option).strip()
            if text and text not in normalized and text not in {"Lewati", "Lainnya"}:
                normalized.append(text)
        normalized = normalized[:5]
        normalized.extend(["Lewati", "Lainnya"])
        return normalized
```

- [ ] **Step 5: Apply normalizer to suggested and LLM options**

When returning suggested question:

```python
options = self._normalize_options(suggested_options)
return ClarifyingQuestionData(
    clarifying_question=suggested_question,
    options=options,
    default_if_no_answer="Lewati",
    ambiguity_type=ambiguity_type,
    ambiguous_phrase=ambiguous_phrase,
    metadata=metadata or {},
)
```

In `_generate_via_llm`, after reading `options`, call `options = self._normalize_options(options)`. Return with `ambiguous_phrase=ambiguous_phrase` and `metadata=metadata or {}`. Update `_generate_via_llm` signature to accept those two values.

- [ ] **Step 6: Update default clarification mappings**

Replace old keys with PRD taxonomy keys:

```python
defaults = {
    "AmbiSchema": {
        "question": "Metrik KPI mana yang Anda maksud?",
        "options": ["Achievement %", "Nilai realisasi", "Target KPI"],
        "default": "Lewati",
    },
    "AmbiValue": {
        "question": "Entri data mana yang paling sesuai dengan maksud Anda?",
        "options": ["Gunakan nilai yang paling mirip", "Tampilkan semua kemungkinan"],
        "default": "Lewati",
    },
    "AmbiIntent": {
        "question": "Bagaimana data KPI ini ingin ditampilkan?",
        "options": ["Daftar detail", "Ranking tertinggi", "Dikelompokkan per divisi", "Total/ringkasan"],
        "default": "Lewati",
    },
    "AmbiContext": {
        "question": "Konteks tambahan mana yang perlu digunakan?",
        "options": ["Hanya data aktif", "Semua data", "Sesuai divisi saya"],
        "default": "Lewati",
    },
    "AmbiFallacy": {
        "question": "Jika data yang diminta tidak tersedia, bagaimana sistem harus melanjutkan?",
        "options": ["Tampilkan data yang tersedia", "Batalkan pertanyaan ini"],
        "default": "Lewati",
    },
    "AmbiRef": {
        "question": "Periode atau referensi waktu mana yang Anda maksud?",
        "options": ["Bulan ini", "Tahun berjalan", "Tahun kalender sebelumnya"],
        "default": "Lewati",
    },
}
```

Return default options through `_normalize_options`.

- [ ] **Step 7: Run generator tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_question_generator_appends_skip_and_other_to_suggested_options tests/clarificationMechanism_test.py::test_question_generator_limits_options_before_defaults tests/clarificationMechanism_test.py::test_generate_question_llm_error_fallback -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add service/clarificationQuestionGeneratorService.py tests/clarificationMechanism_test.py
git commit -m "feat: normalize KPI clarification options"
```

---

### Task 6: Make clarification question storage session-aware and text-preserving

**Files:**
- Modify: `model/ClarificationQuestion.py`
- Modify: `alembic/versions/6fac3aac3721_replace_chat_schema.py`
- Modify: `repository/clarificationRepository.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add repository behavior tests with mocked DB boundaries**

Append:

```python
def test_clarification_repository_preserves_text_answer():
    repo = ClarificationRepository(db=None)

    assert repo._serialize_answer("Achievement %") == "Achievement %"
    assert repo._serialize_answer("Lewati") == "Lewati"
    assert repo._serialize_answer(None) is None


def test_clarification_repository_serializes_options_as_json():
    repo = ClarificationRepository(db=None)

    serialized = repo._serialize_options(["Achievement %", "Lewati", "Lainnya"])

    assert serialized == '["Achievement %", "Lewati", "Lainnya"]'
```

Add import if missing:

```python
from repository.clarificationRepository import ClarificationRepository
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_repository_preserves_text_answer tests/clarificationMechanism_test.py::test_clarification_repository_serializes_options_as_json -v
```

Expected: FAIL because helpers do not exist.

- [ ] **Step 3: Update `model/ClarificationQuestion.py` columns**

Change imports:

```python
from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy import UUID as SAUUID
```

Add fields after `answer_options`:

```python
    selected_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    free_text_answer: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

Add session field after `message_id`:

```python
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        SAUUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
```

Update property:

```python
    @property
    def clarification_answer(self) -> str | int | None:
        return self.selected_answer if self.selected_answer is not None else self.user_answer
```

- [ ] **Step 4: Update replacement migration table columns**

In `alembic/versions/6fac3aac3721_replace_chat_schema.py`, add after `answer_options`:

```python
        sa.Column("selected_answer", sa.String(length=255), nullable=True),
        sa.Column("free_text_answer", sa.String(length=255), nullable=True),
```

Add after `message_id`:

```python
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
```

Add FK constraint:

```python
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"
        ),
```

Add index after message index:

```python
    op.create_index(
        "ix_clarification_questions_session_id",
        "clarification_questions",
        ["session_id"],
    )
```

Drop it in downgrade before dropping table:

```python
    op.drop_index("ix_clarification_questions_session_id", table_name="clarification_questions")
```

- [ ] **Step 5: Update repository helpers**

In `repository/clarificationRepository.py`, add:

```python
    @staticmethod
    def _serialize_options(answer_options: list[str] | None) -> str | None:
        if not answer_options:
            return None
        return json.dumps(answer_options, ensure_ascii=False)[:255]

    @staticmethod
    def _serialize_answer(clarification_answer: str | None) -> str | None:
        if clarification_answer is None:
            return None
        return str(clarification_answer)[:255]
```

- [ ] **Step 6: Update repository create/update/query methods**

In `create`, set:

```python
            answer_options=self._serialize_options(answer_options),
            selected_answer=self._serialize_answer(clarification_answer),
            user_answer=self._parse_user_answer(clarification_answer),
            message_id=message_id,
            session_id=session_id,
```

In `update_with_answer`, add optional `free_text_answer: str | None = None` parameter and set:

```python
        question.selected_answer = self._serialize_answer(clarification_answer)
        question.free_text_answer = self._serialize_answer(free_text_answer)
        question.user_answer = self._parse_user_answer(clarification_answer)
```

In `get_by_session`, add filter:

```python
        stmt = (
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
        )
```

In `get_last_clarification`, add filter:

```python
        stmt = (
            select(ClarificationQuestion)
            .where(ClarificationQuestion.session_id == session_id)
            .order_by(desc(ClarificationQuestion.created_at))
            .limit(1)
        )
```

- [ ] **Step 7: Run repository helper tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_repository_preserves_text_answer tests/clarificationMechanism_test.py::test_clarification_repository_serializes_options_as_json -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add model/ClarificationQuestion.py alembic/versions/6fac3aac3721_replace_chat_schema.py repository/clarificationRepository.py tests/clarificationMechanism_test.py
git commit -m "feat: store session-scoped clarification answers"
```

---

### Task 7: Orchestrate batched clarification service

**Files:**
- Modify: `service/clarificationService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing service batch test**

Append:

```python
@pytest.mark.asyncio
async def test_process_user_query_returns_batched_questions():
    service = ClarificationService(db=None)
    service.repo.create = AsyncMock(side_effect=[
        SimpleNamespace(clarification_question_id="q1"),
        SimpleNamespace(clarification_question_id="q2"),
    ])

    service.context_service.build_context = lambda: "KPI context"

    with patch.object(service.ambiguity_detector, 'detect_ambiguity', new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiSchema",
            ambiguity_score=0.92,
            detection_source="llm",
            detected_ambiguities=[
                DetectedAmbiguity(
                    ambiguous_phrase="terbaik",
                    ambiguity_type="AmbiSchema",
                    ambiguity_score=0.92,
                    suggested_clarifying_question="Metrik terbaik mana?",
                    answer_options=["Achievement %", "Realisasi"],
                ),
                DetectedAmbiguity(
                    ambiguous_phrase="tahun lalu",
                    ambiguity_type="AmbiRef",
                    ambiguity_score=0.88,
                    suggested_clarifying_question="Periode tahun lalu mana?",
                    answer_options=["Calendar Year 2025", "Fiscal Year 2025"],
                ),
            ],
        )

        result = await service.process_user_query(
            user_query="Tampilkan sales terbaik tahun lalu",
            user_id=uuid4(),
            user_role="Kepala Divisi",
            session_id=SESSION_TEST_2,
            clarification_count=0,
        )

    assert result is not None
    assert result.questions is not None
    assert len(result.questions) == 2
    assert result.questions[0].options[-2:] == ["Lewati", "Lainnya"]
    assert service.repo.create.await_count == 2
```

- [ ] **Step 2: Run service test to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_process_user_query_returns_batched_questions -v
```

Expected: FAIL because `context_service` and batched `questions` orchestration do not exist.

- [ ] **Step 3: Update imports and constructor**

In `service/clarificationService.py`, import:

```python
from schema.clarificationSchema import (
    QueryDisambiguationResult,
    ClarificationMessageResponse,
    ClarificationQuestionResponse,
    ClarificationAnswerItem,
)
from service.kpiAmbiguityContextService import KPIAmbiguityContextService
```

In `__init__`, add:

```python
        self.context_service = KPIAmbiguityContextService()
        self.MAX_QUESTIONS_PER_BATCH = 3
```

- [ ] **Step 4: Update `process_user_query` to build batch**

Replace the single-question generation branch with:

```python
        kpi_context = self.context_service.build_context()
        ambiguity_result = await self.ambiguity_detector.detect_ambiguity(
            user_query, user_role, kpi_context
        )
```

After direct-answer branch, add:

```python
        detected = sorted(
            ambiguity_result.detected_ambiguities,
            key=lambda item: item.ambiguity_score,
            reverse=True,
        )[: self.MAX_QUESTIONS_PER_BATCH]

        questions: list[ClarificationQuestionResponse] = []
        for ambiguity in detected:
            clarifying_q = await self.question_generator.generate_clarifying_question(
                user_query=user_query,
                ambiguity_type=ambiguity.ambiguity_type,
                possible_interpretations=ambiguity.possible_interpretations,
                suggested_question=ambiguity.suggested_clarifying_question,
                suggested_options=ambiguity.answer_options,
                user_role=user_role,
                ambiguous_phrase=ambiguity.ambiguous_phrase,
                metadata=ambiguity.metadata,
            )
            log = await self.repo.create(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                original_query=user_query,
                ambiguity_score=ambiguity.ambiguity_score,
                ambiguity_type=ambiguity.ambiguity_type,
                decision="clarify",
                decision_source=ambiguity_result.detection_source,
                clarifying_question=clarifying_q.clarifying_question,
                answer_options=clarifying_q.options,
            )
            questions.append(
                ClarificationQuestionResponse(
                    id=str(log.clarification_question_id),
                    ambiguous_phrase=clarifying_q.ambiguous_phrase,
                    ambiguity_type=clarifying_q.ambiguity_type,
                    question=clarifying_q.clarifying_question,
                    options=clarifying_q.options,
                    metadata=clarifying_q.metadata,
                )
            )

        return ClarificationMessageResponse(
            session_id=session_id,
            message_type="clarification",
            clarifying_question=questions[0].question if questions else None,
            options=questions[0].options if questions else None,
            questions=questions,
        )
```

Keep the direct branch logging as-is, but ensure fallback result has `detected_ambiguities=[]` so no batch is produced.

- [ ] **Step 5: Run service batch test**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_process_user_query_returns_batched_questions -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add service/clarificationService.py tests/clarificationMechanism_test.py
git commit -m "feat: return batched clarification questions"
```

---

### Task 8: Rewrite query from batched answers

**Files:**
- Modify: `service/clarificationService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add failing batched rewrite test**

Append:

```python
@pytest.mark.asyncio
async def test_handle_clarification_response_rewrites_from_batched_answers():
    service = ClarificationService(db=None)
    service.repo.get_by_session = AsyncMock(return_value=[
        SimpleNamespace(
            clarification_question_id="q1",
            ambiguous_phrase="Tampilkan sales terbaik tahun lalu",
            clarification_question="Metrik terbaik mana?",
        ),
        SimpleNamespace(
            clarification_question_id="q2",
            ambiguous_phrase="Tampilkan sales terbaik tahun lalu",
            clarification_question="Periode mana?",
        ),
    ])
    service.repo.update_with_answer = AsyncMock()

    with patch.object(service.llm, '_call_llm', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "Tampilkan sales dengan Achievement % tertinggi untuk Calendar Year 2025 hanya divisi aktif"

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Achievement %"),
                ClarificationAnswerItem(question_id="q2", selected_option="Calendar Year 2025"),
            ],
            additional_constraints="hanya divisi aktif",
        )

    assert "Achievement %" in result.disambiguated_query
    assert "Calendar Year 2025" in result.disambiguated_query
    assert service.repo.update_with_answer.await_count == 2
```

- [ ] **Step 2: Run rewrite test to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_handle_clarification_response_rewrites_from_batched_answers -v
```

Expected: FAIL because method accepts a single answer string.

- [ ] **Step 3: Update `handle_clarification_response` signature and logic**

Change signature:

```python
async def handle_clarification_response(
    self,
    session_id: UUID,
    clarification_answers: list[ClarificationAnswerItem],
    additional_constraints: str | None = None,
) -> QueryDisambiguationResult:
```

Implement:

```python
        logs = await self.repo.get_by_session(session_id)
        if not logs:
            raise ValueError(f"Tidak ada pertanyaan klarifikasi untuk session {session_id}")

        log_by_id = {str(log.clarification_question_id): log for log in logs}
        missing = [answer.question_id for answer in clarification_answers if answer.question_id not in log_by_id]
        if missing:
            raise ValueError(f"Pertanyaan klarifikasi tidak ditemukan: {', '.join(missing)}")

        original_query = logs[0].ambiguous_phrase or ""
        disambiguated_query = await self._disambiguate_query(
            original_query=original_query,
            clarification_answers=clarification_answers,
            additional_constraints=additional_constraints,
        )

        for answer in clarification_answers:
            effective_answer = answer.free_text if answer.selected_option == "Lainnya" and answer.free_text else answer.selected_option
            await self.repo.update_with_answer(
                log_id=answer.question_id,
                clarification_answer=effective_answer,
                disambiguated_query=disambiguated_query,
                free_text_answer=answer.free_text,
            )

        return QueryDisambiguationResult(
            original_query=original_query,
            clarification_answers=clarification_answers,
            disambiguated_query=disambiguated_query,
            additional_constraints=additional_constraints,
        )
```

- [ ] **Step 4: Update `_disambiguate_query` signature and call**

Change signature:

```python
async def _disambiguate_query(
    self,
    original_query: str,
    clarification_answers: list[ClarificationAnswerItem],
    additional_constraints: str | None = None,
) -> str:
```

Build prompt:

```python
prompt = build_query_disambiguation_prompt(
    original_query=original_query,
    clarification_answers=clarification_answers,
    additional_constraints=additional_constraints,
)
```

Update fallback call:

```python
return self._build_fallback_disambiguated_query(original_query, clarification_answers, additional_constraints)
```

- [ ] **Step 5: Replace fallback builder**

Change signature and body:

```python
def _build_fallback_disambiguated_query(
    self,
    original_query: str,
    clarification_answers: list[ClarificationAnswerItem],
    additional_constraints: str | None = None,
) -> str:
    query = original_query.strip()
    additions: list[str] = []
    for answer in clarification_answers:
        if answer.selected_option == "Lewati":
            continue
        if answer.selected_option == "Lainnya" and answer.free_text:
            additions.append(answer.free_text.strip())
        else:
            additions.append(answer.selected_option.strip())
    if additional_constraints:
        additions.append(additional_constraints.strip())
    if not additions:
        return query
    return f"{query} ({'; '.join(additions)})"
```

- [ ] **Step 6: Run rewrite tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_handle_clarification_response_rewrites_from_batched_answers -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service/clarificationService.py tests/clarificationMechanism_test.py
git commit -m "feat: rewrite KPI query from batched answers"
```

---

### Task 9: Wire batched clarification into controller and chat service

**Files:**
- Modify: `controller/chatController.py`
- Modify: `service/chatService.py`
- Modify: `schema/chatSchema.py`
- Test: `tests/chatPipeline_test.py`
- Test: `tests/chatStreaming_test.py`

- [ ] **Step 1: Add failing chat service test**

In `tests/chatPipeline_test.py`, add a focused unit test using mocks around `ChatService.process_query`. If the file already has fixtures for `ChatService`, adapt the setup; otherwise append:

```python
@pytest.mark.asyncio
async def test_chat_service_returns_batched_clarification_questions(monkeypatch):
    from service.chatService import ChatService
    from schema.clarificationSchema import ClarificationMessageResponse, ClarificationQuestionResponse

    service = ChatService(db=None)
    service.session_service.create_session_if_missing = AsyncMock()

    async def fake_process_user_query(*args, **kwargs):
        return ClarificationMessageResponse(
            session_id=SESSION_TEST_1,
            questions=[
                ClarificationQuestionResponse(
                    id="q1",
                    ambiguous_phrase="terbaik",
                    ambiguity_type="AmbiSchema",
                    question="Metrik terbaik mana?",
                    options=["Achievement %", "Lewati", "Lainnya"],
                )
            ],
        )

    class FakeClarificationService:
        def __init__(self, db):
            pass
        async def get_clarification_count_in_session(self, session_id):
            return 0
        async def process_user_query(self, *args, **kwargs):
            return await fake_process_user_query(*args, **kwargs)

    monkeypatch.setattr("service.clarificationService.ClarificationService", FakeClarificationService)

    response = await service.process_query(
        user_message="Tampilkan sales terbaik",
        user_id=uuid4(),
        user_role="Kepala Divisi",
        user_divisi=None,
        session_id=SESSION_TEST_1,
    )

    assert response.clarification_questions is not None
    assert response.clarification_questions[0].id == "q1"
```

- [ ] **Step 2: Run chat service test to verify failure**

Run:

```bash
pytest tests/chatPipeline_test.py::test_chat_service_returns_batched_clarification_questions -v
```

Expected: FAIL because response does not populate `clarification_questions`.

- [ ] **Step 3: Update `service/chatService.py` clarification response**

In the Stage 0 clarification return, replace the `ChatResponse` construction with:

```python
return ChatResponse(
    session_id=session_id,
    message=clarification_response.clarifying_question or "Klarifikasi diperlukan sebelum query KPI dijalankan.",
    clarification_message_answer_options=clarification_response.options,
    clarification_questions=clarification_response.questions,
    pipeline_stages=stages,
)
```

Keep `context_from_clarification` skip logic as-is.

- [ ] **Step 4: Update controller clarification handler**

In `controller/chatController.py`, replace validation:

```python
if not request.session_id or not request.clarification_answers:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="session_id dan clarification_answers wajib disertakan",
    )
```

Replace service call:

```python
disambiguation_result = await clarification_service.handle_clarification_response(
    session_id=request.session_id,
    clarification_answers=request.clarification_answers,
    additional_constraints=request.additional_constraints,
)
```

- [ ] **Step 5: Run chat service test**

Run:

```bash
pytest tests/chatPipeline_test.py::test_chat_service_returns_batched_clarification_questions -v
```

Expected: PASS.

- [ ] **Step 6: Run streaming tests that touch chat metadata**

Run:

```bash
pytest tests/chatStreaming_test.py -v
```

Expected: PASS or only failures unrelated to clarification metadata. If metadata assertions fail, update expected metadata to include `clarification_questions`.

- [ ] **Step 7: Commit**

```bash
git add controller/chatController.py service/chatService.py schema/chatSchema.py tests/chatPipeline_test.py tests/chatStreaming_test.py
git commit -m "feat: wire batched clarification into chat API"
```

---

### Task 10: Add end-to-end clarification service scenarios

**Files:**
- Modify: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add tests for `Lewati`, `Lainnya`, and question limit**

Append:

```python
@pytest.mark.asyncio
async def test_fallback_rewrite_skips_lewati_and_uses_lainnya():
    service = ClarificationService(db=None)

    result = service._build_fallback_disambiguated_query(
        original_query="Tampilkan performa terbaik",
        clarification_answers=[
            ClarificationAnswerItem(question_id="q1", selected_option="Lewati"),
            ClarificationAnswerItem(question_id="q2", selected_option="Lainnya", free_text="gunakan weighted score"),
        ],
        additional_constraints="hanya divisi aktif",
    )

    assert "Lewati" not in result
    assert "weighted score" in result
    assert "hanya divisi aktif" in result


@pytest.mark.asyncio
async def test_process_user_query_limits_batch_to_three_questions():
    service = ClarificationService(db=None)
    service.repo.create = AsyncMock(side_effect=[
        SimpleNamespace(clarification_question_id="q1"),
        SimpleNamespace(clarification_question_id="q2"),
        SimpleNamespace(clarification_question_id="q3"),
    ])
    service.context_service.build_context = lambda: "KPI context"

    ambiguities = [
        DetectedAmbiguity(
            ambiguous_phrase=f"phrase-{index}",
            ambiguity_type="AmbiSchema",
            ambiguity_score=0.95 - (index * 0.01),
            suggested_clarifying_question=f"Question {index}?",
            answer_options=["A", "B"],
        )
        for index in range(5)
    ]

    with patch.object(service.ambiguity_detector, 'detect_ambiguity', new_callable=AsyncMock) as mock_detect:
        mock_detect.return_value = AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiSchema",
            ambiguity_score=0.95,
            detection_source="llm",
            detected_ambiguities=ambiguities,
        )

        result = await service.process_user_query(
            user_query="Query ambigu",
            user_id=uuid4(),
            user_role="Admin",
            session_id=SESSION_TEST_3,
        )

    assert result.questions is not None
    assert len(result.questions) == 3
```

- [ ] **Step 2: Run new scenario tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_fallback_rewrite_skips_lewati_and_uses_lainnya tests/clarificationMechanism_test.py::test_process_user_query_limits_batch_to_three_questions -v
```

Expected: PASS.

- [ ] **Step 3: Run full clarification test file**

Run:

```bash
pytest tests/clarificationMechanism_test.py -v
```

Expected: PASS. If legacy tests fail because they still expect `scope` taxonomy or single-answer signatures, update them to `AmbiSchema`/`AmbiRef` and batched answers while preserving the original behavior being tested.

- [ ] **Step 4: Commit**

```bash
git add tests/clarificationMechanism_test.py
git commit -m "test: cover KPI clarification batch scenarios"
```

---

### Task 11: Final verification

**Files:**
- Potentially modify files only for fixes found by tests.

- [ ] **Step 1: Run targeted test suite**

Run:

```bash
pytest tests/clarificationMechanism_test.py tests/chatPipeline_test.py tests/chatStreaming_test.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader tests if targeted tests pass**

Run:

```bash
pytest -q
```

Expected: PASS or known unrelated failures. Investigate any clarification/chat failures before proceeding.

- [ ] **Step 3: Inspect git diff**

Run:

```bash
git diff --stat
```

Expected: changes are limited to schema, service, repository/model/migration, controller, prompt template, and tests listed in this plan.

- [ ] **Step 4: Commit final fixes if any**

If Step 1 or Step 2 required fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize KPI clarification batch flow"
```

If no fixes were needed, do not create an empty commit.

---

## Self-review notes

- Spec coverage: tasks cover multi-ambiguity detection, PRD taxonomy, KPI context grounding, batched response, batched answers, rewrite, storage, fallback behavior, limits, and tests.
- Deferred non-goals remain deferred: frontend panel, preference settings, SQL visual diff, automatic resolution, multi-data-source selection.
- Type consistency: the plan consistently uses `DetectedAmbiguity`, `ClarificationQuestionResponse`, `ClarificationAnswerItem`, `ClarificationMessageResponse.questions`, and `ChatResponse.clarification_questions`.
