# Remove Ambiguous Phrase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `ambiguous_phrase` from `clarification_questions` persistence, ORM model, API schemas, services, repositories, and tests.

**Architecture:** Treat `ambiguous_phrase` as removed public and persisted data. Clarification identity now relies on `ambiguity_type`, `clarification_question`, answer options, and session/message links. Migration drops nullable column and downgrade restores it as nullable `String(255)`.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async ORM, Alembic, pytest.

---

## File Structure

- Modify `model/ClarificationQuestion.py`: remove ORM column.
- Modify `schema/clarificationSchema.py`: remove API/internal schema fields and example key.
- Modify `repository/clarificationRepository.py`: keep create signature free of removed field; no DB write for removed field.
- Modify `service/clarificationService.py`: remove reads/writes/mapping of removed field; use `original_query` fallback when handling answers.
- Modify `service/ambiguityDetectorService.py`: remove `ambiguous_phrase=None` from `DetectedAmbiguity` construction once schema field is gone.
- Create `alembic/versions/<revision>_drop_ambiguous_phrase_from_clarification_questions.py`: drop/add column.
- Modify tests that build or assert `ambiguous_phrase`: `tests/clarificationMechanism_test.py`, `tests/chatStreaming_test.py`, and any other grep hits.

---

### Task 1: Add failing schema/model tests

**Files:**
- Modify: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Update model test expectation**

Replace test that expects `ambiguous_phrase` to exist, or add this focused assertion near existing model column tests:

```python
def test_clarification_question_has_no_ambiguous_phrase_column():
    """ClarificationQuestion no longer persists ambiguous phrase."""
    from model.ClarificationQuestion import ClarificationQuestion

    assert ClarificationQuestion.__table__.columns.get("ambiguous_phrase") is None
```

- [ ] **Step 2: Add response schema rejection test**

Add this test near clarification schema tests:

```python
def test_clarification_question_response_excludes_ambiguous_phrase():
    from schema.clarificationSchema import ClarificationQuestionResponse

    response = ClarificationQuestionResponse(
        id="q1",
        ambiguity_type="AmbiSchema",
        question="Metrik mana yang dimaksud?",
        options=["Achievement %", "Total realisasi"],
    )

    assert "ambiguous_phrase" not in response.model_dump()
```

- [ ] **Step 3: Run tests to verify failure before implementation**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_question_has_no_ambiguous_phrase_column tests/clarificationMechanism_test.py::test_clarification_question_response_excludes_ambiguous_phrase -v
```

Expected: first test FAILS because column still exists; second test FAILS because schema still includes `ambiguous_phrase`.

---

### Task 2: Remove model and schema fields

**Files:**
- Modify: `model/ClarificationQuestion.py`
- Modify: `schema/clarificationSchema.py`

- [ ] **Step 1: Remove ORM column**

In `model/ClarificationQuestion.py`, delete:

```python
    ambiguous_phrase: Mapped[str | None] = mapped_column(String(255), nullable=True)
```

- [ ] **Step 2: Remove `DetectedAmbiguity.ambiguous_phrase`**

In `schema/clarificationSchema.py`, change `DetectedAmbiguity` from:

```python
class DetectedAmbiguity(BaseModel):
    """Single detected ambiguity with PRD-aligned taxonomy."""
    ambiguous_phrase: str | None = None
    ambiguity_type: str
    possible_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

to:

```python
class DetectedAmbiguity(BaseModel):
    """Single detected ambiguity with PRD-aligned taxonomy."""
    ambiguity_type: str
    possible_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    suggested_clarifying_question: str | None = None
    answer_options: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 3: Remove response field**

In `schema/clarificationSchema.py`, change `ClarificationQuestionResponse` from:

```python
class ClarificationQuestionResponse(BaseModel):
    """Single clarification question in batched response."""
    id: str
    ambiguous_phrase: str | None = None
    ambiguity_type: str
    question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

to:

```python
class ClarificationQuestionResponse(BaseModel):
    """Single clarification question in batched response."""
    id: str
    ambiguity_type: str
    question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Remove generated question data field**

In `schema/clarificationSchema.py`, change `ClarifyingQuestionData` from:

```python
class ClarifyingQuestionData(BaseModel):
    """Data pertanyaan klarifikasi yang siap dikirim ke user."""
    clarifying_question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    default_if_no_answer: str
    ambiguity_type: str
    ambiguous_phrase: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

to:

```python
class ClarifyingQuestionData(BaseModel):
    """Data pertanyaan klarifikasi yang siap dikirim ke user."""
    clarifying_question: str
    options: List[str] = Field(..., min_length=2, max_length=7)
    default_if_no_answer: str
    ambiguity_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 5: Remove example key**

In `ClarificationMessageResponse.model_config`, change example question from:

```python
                {
                    "id": "q1",
                    "ambiguous_phrase": "terbaik",
                    "ambiguity_type": "AmbiSchema",
                    "question": "'Terbaik' merujuk ke metrik apa?",
                    "options": ["Achievement %", "Total realisasi", "Lewati", "Lainnya"],
                }
```

to:

```python
                {
                    "id": "q1",
                    "ambiguity_type": "AmbiSchema",
                    "question": "'Terbaik' merujuk ke metrik apa?",
                    "options": ["Achievement %", "Total realisasi", "Lewati", "Lainnya"],
                }
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_question_has_no_ambiguous_phrase_column tests/clarificationMechanism_test.py::test_clarification_question_response_excludes_ambiguous_phrase -v
```

Expected: PASS.

---

### Task 3: Remove service and detector usage

**Files:**
- Modify: `service/clarificationService.py`
- Modify: `service/ambiguityDetectorService.py`

- [ ] **Step 1: Remove source query dependency on deleted column**

In `service/clarificationService.py`, change:

```python
        source_query = original_query or logs[-1].ambiguous_phrase or ""
```

to:

```python
        source_query = original_query or ""
```

- [ ] **Step 2: Remove ambiguous phrase from QA level2 fallback**

Change:

```python
                    level2=getattr(log, "ambiguous_phrase", None) or getattr(
                        log, "clarification_question", None) or answer.question_id,
```

to:

```python
                    level2=getattr(log, "clarification_question", None) or answer.question_id,
```

- [ ] **Step 3: Remove generator argument and returned field use**

In `_build_clarification_response_from_detection`, change:

```python
            clarifying_q = await self._generate_clarifying_question(
                ambiguity_type=ambiguity.ambiguity_type,
                suggested_question=ambiguity.suggested_clarifying_question,
                suggested_options=ambiguity.answer_options,
                ambiguous_phrase=ambiguity.ambiguous_phrase,
                metadata=ambiguity.metadata,
            )
```

to:

```python
            clarifying_q = await self._generate_clarifying_question(
                ambiguity_type=ambiguity.ambiguity_type,
                suggested_question=ambiguity.suggested_clarifying_question,
                suggested_options=ambiguity.answer_options,
                metadata=ambiguity.metadata,
            )
```

- [ ] **Step 4: Remove repository create kwargs no longer accepted**

In same method, change:

```python
            log = await self.repo.create(
                session_id=session_id,
                original_query=original_query,
                ambiguity_type=ambiguity.ambiguity_type,
                is_ambiguity_level1_type_llm=ambiguity.metadata.get(
                    "is_ambiguity_level1_type_llm"),
                clarifying_question=clarifying_q.clarifying_question,
                answer_options=clarifying_q.options,
                ambiguous_phrase=clarifying_q.ambiguous_phrase,
            )
```

to:

```python
            log = await self.repo.create(
                session_id=session_id,
                ambiguity_type=ambiguity.ambiguity_type,
                is_ambiguity_level1_type_llm=ambiguity.metadata.get(
                    "is_ambiguity_level1_type_llm"),
                clarifying_question=clarifying_q.clarifying_question,
                answer_options=clarifying_q.options,
            )
```

- [ ] **Step 5: Remove response field mapping**

Change:

```python
                ClarificationQuestionResponse(
                    id=str(log.clarification_question_id),
                    ambiguous_phrase=clarifying_q.ambiguous_phrase or ambiguity.ambiguous_phrase,
                    ambiguity_type=clarifying_q.ambiguity_type or ambiguity.ambiguity_type,
                    question=clarifying_q.clarifying_question,
                    options=clarifying_q.options,
                    metadata=getattr(clarifying_q, "metadata", {}),
                )
```

to:

```python
                ClarificationQuestionResponse(
                    id=str(log.clarification_question_id),
                    ambiguity_type=clarifying_q.ambiguity_type or ambiguity.ambiguity_type,
                    question=clarifying_q.clarifying_question,
                    options=clarifying_q.options,
                    metadata=getattr(clarifying_q, "metadata", {}),
                )
```

- [ ] **Step 6: Remove generator parameter and return fields**

Change `_generate_clarifying_question` signature from:

```python
    async def _generate_clarifying_question(
            ambiguity_type: str,
        suggested_question: Optional[str],
        suggested_options: Optional[list[str]],
        ambiguous_phrase: str | None = None,
        metadata: dict | None = None,
    ) -> ClarifyingQuestionData:
```

to:

```python
    async def _generate_clarifying_question(
            ambiguity_type: str,
        suggested_question: Optional[str],
        suggested_options: Optional[list[str]],
        metadata: dict | None = None,
    ) -> ClarifyingQuestionData:
```

Then remove `ambiguous_phrase=ambiguous_phrase,` from both `ClarifyingQuestionData(...)` returns.

- [ ] **Step 7: Remove detector construction field**

In `service/ambiguityDetectorService.py`, change:

```python
                        DetectedAmbiguity(
                            ambiguous_phrase=None,  # Not provided in question_set format
                            ambiguity_type=str(level_2_label),
                            possible_interpretations=possible_interpretations,
                            suggested_clarifying_question=item.get("question"),
                            answer_options=options,  # Raw options, no normalization here
                            metadata={
                                "is_ambiguity_level1_type_llm": is_llm_sourced,
                                "level_1_label": level_1_label,
                            },
                        )
```

to:

```python
                        DetectedAmbiguity(
                            ambiguity_type=str(level_2_label),
                            possible_interpretations=possible_interpretations,
                            suggested_clarifying_question=item.get("question"),
                            answer_options=options,
                            metadata={
                                "is_ambiguity_level1_type_llm": is_llm_sourced,
                                "level_1_label": level_1_label,
                            },
                        )
```

- [ ] **Step 8: Search for remaining usages**

Run:

```bash
grep -R "ambiguous_phrase" -n model repository schema service tests
```

Expected: only unrelated historical text remains. If matches remain in runtime code or tests, remove them before continuing.

---

### Task 4: Add Alembic migration

**Files:**
- Create: `alembic/versions/<new_revision>_drop_ambiguous_phrase_from_clarification_questions.py`

- [ ] **Step 1: Identify current Alembic head**

Run:

```bash
alembic heads
```

Expected: one current head revision. Use that revision as `down_revision`.

- [ ] **Step 2: Create migration file**

Create a file like `alembic/versions/<new_revision>_drop_ambiguous_phrase_from_clarification_questions.py` with this structure, replacing `<new_revision>` and `<down_revision>`:

```python
"""drop ambiguous_phrase from clarification_questions

Revision ID: <new_revision>
Revises: <down_revision>
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "<new_revision>"
down_revision: Union[str, Sequence[str], None] = "<down_revision>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("clarification_questions", "ambiguous_phrase")


def downgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("ambiguous_phrase", sa.String(length=255), nullable=True),
    )
```

Use a 12-character lowercase hex-style revision id not already present in `alembic/versions`.

- [ ] **Step 3: Verify migration syntax**

Run:

```bash
python -m py_compile alembic/versions/<new_revision>_drop_ambiguous_phrase_from_clarification_questions.py
```

Expected: command exits 0 with no output.

---

### Task 5: Update tests and fixtures that send field

**Files:**
- Modify: `tests/clarificationMechanism_test.py`
- Modify: `tests/chatStreaming_test.py`
- Modify: any other test files found by search.

- [ ] **Step 1: Remove `ambiguous_phrase=` from schema constructors**

Change constructors like:

```python
ClarificationQuestionResponse(
    id="q1",
    ambiguous_phrase="achievement",
    ambiguity_type="AmbiSchema",
    question="Metrik mana yang dimaksud?",
    options=["Achievement %", "Total realisasi"],
)
```

to:

```python
ClarificationQuestionResponse(
    id="q1",
    ambiguity_type="AmbiSchema",
    question="Metrik mana yang dimaksud?",
    options=["Achievement %", "Total realisasi"],
)
```

- [ ] **Step 2: Remove `ambiguous_phrase=` from `DetectedAmbiguity` constructors**

Change constructors like:

```python
DetectedAmbiguity(
    ambiguous_phrase="terbaik",
    ambiguity_type="AmbiSchema",
    possible_interpretations=[{"text": "Achievement %"}],
    suggested_clarifying_question="Metrik mana yang dimaksud?",
    answer_options=["Achievement %", "Total realisasi"],
)
```

to:

```python
DetectedAmbiguity(
    ambiguity_type="AmbiSchema",
    possible_interpretations=[{"text": "Achievement %"}],
    suggested_clarifying_question="Metrik mana yang dimaksud?",
    answer_options=["Achievement %", "Total realisasi"],
)
```

- [ ] **Step 3: Remove assertions expecting field in dumps/responses**

Delete assertions like:

```python
assert question.ambiguous_phrase == "terbaik"
assert response.questions[0].ambiguous_phrase == "terbaik"
assert data["questions"][0]["ambiguous_phrase"] == "terbaik"
```

Replace response-shape assertions with:

```python
assert "ambiguous_phrase" not in response.questions[0].model_dump()
```

or, for dict payloads:

```python
assert "ambiguous_phrase" not in data["questions"][0]
```

- [ ] **Step 4: Search tests again**

Run:

```bash
grep -R "ambiguous_phrase" -n tests
```

Expected: only `test_clarification_question_has_no_ambiguous_phrase_column` and `test_clarification_question_response_excludes_ambiguous_phrase` remain.

---

### Task 6: Run verification

**Files:**
- Test only.

- [ ] **Step 1: Run focused clarification tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py tests/chatStreaming_test.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader impacted tests**

Run:

```bash
pytest tests/chatPipeline_test.py tests/clarificationMechanism_test.py tests/chatStreaming_test.py -v
```

Expected: PASS.

- [ ] **Step 3: Verify no runtime usage remains**

Run:

```bash
grep -R "ambiguous_phrase" -n model repository schema service tests
```

Expected: only the two negative tests remain.

- [ ] **Step 4: Review diff**

Run:

```bash
git diff -- model/ClarificationQuestion.py schema/clarificationSchema.py repository/clarificationRepository.py service/clarificationService.py service/ambiguityDetectorService.py tests/clarificationMechanism_test.py tests/chatStreaming_test.py alembic/versions
```

Expected: diff only removes `ambiguous_phrase`, adds drop-column migration, and updates tests.

---

## Self-Review

- Spec coverage: DB migration, model, API schemas, services/repositories, and tests are covered.
- Placeholder scan: no TBD/TODO/implement later placeholders remain.
- Type consistency: removed `ambiguous_phrase` from Pydantic constructors before service/test calls are updated.
