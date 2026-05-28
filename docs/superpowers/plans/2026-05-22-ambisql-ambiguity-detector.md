# AmbiSQL Ambiguity Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current ambiguity detector prompt/parser with AmbiSQL-style detection while keeping the existing clarification pipeline contract intact.

**Architecture:** `template/promptTemplate.py` will produce paper-aligned `has_ambiguity/question_set` JSON. `service/ambiguityDetectorService.py` will adapt that format into existing `AmbiguityAssessmentResult`/`DetectedAmbiguity` objects. Persistence will add nullable `is_ambiguity_level1_type_llm` to `clarification_questions`, and `ClarificationService`/repository will pass the detector metadata through without moving CQ generation into the detector.

**Tech Stack:** FastAPI backend, Python 3.10+, Pydantic, SQLAlchemy async ORM, Alembic, pytest/pytest-asyncio.

---

## File Structure

- Modify `schema/clarificationSchema.py`: add `AmbiIntent`, keep no `AmbiSource`, and add optional `is_ambiguity_level1_type_llm` to internal/API log models where appropriate.
- Modify `template/promptTemplate.py`: rewrite `build_ambiguity_assessment_prompt()` to AmbiSQL-style prompt with `Question`, `Schema`, `Evidence`.
- Modify `service/ambiguityDetectorService.py`: parse `has_ambiguity/question_set`, map `description.options`, skip unsupported labels, preserve detector/CQ separation.
- Modify `model/ClarificationQuestion.py`: add nullable boolean column `is_ambiguity_level1_type_llm`.
- Modify `repository/clarificationRepository.py`: accept and persist `is_ambiguity_level1_type_llm`.
- Modify `service/clarificationService.py`: pass `ambiguity.metadata["is_ambiguity_level1_type_llm"]` into repository create calls.
- Create Alembic migration under `alembic/versions/`: add/drop `clarification_questions.is_ambiguity_level1_type_llm`.
- Modify `service/clarificationQuestionGeneratorService.py`: add `AmbiIntent` fallback and remove any expectation of unsupported ambiguity types.
- Modify/add tests in `tests/clarificationMechanism_test.py`: cover parser mapping and persistence handoff.

---

### Task 1: Update taxonomy schema and CQ fallback

**Files:**
- Modify: `schema/clarificationSchema.py:16-24`
- Modify: `service/clarificationQuestionGeneratorService.py:138-168`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing taxonomy test**

Add this test to `tests/clarificationMechanism_test.py`:

```python
def test_prd_ambiguity_types_use_ambiintent_not_ambisource():
    from schema.clarificationSchema import PRD_AMBIGUITY_TYPES

    assert "AmbiIntent" in PRD_AMBIGUITY_TYPES
    assert "AmbiSource" not in PRD_AMBIGUITY_TYPES
    assert "AmbiView" not in PRD_AMBIGUITY_TYPES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/clarificationMechanism_test.py::test_prd_ambiguity_types_use_ambiintent_not_ambisource -v`

Expected: FAIL if taxonomy still lacks the exact desired set.

- [ ] **Step 3: Update taxonomy set**

In `schema/clarificationSchema.py`, replace `PRD_AMBIGUITY_TYPES` with:

```python
PRD_AMBIGUITY_TYPES = {
    "AmbiSchema",
    "AmbiValue",
    "AmbiIntent",
    "AmbiContext",
    "AmbiFallacy",
    "AmbiRef",
    "none",
}
```

- [ ] **Step 4: Update CQ fallback key**

In `service/clarificationQuestionGeneratorService.py`, ensure the fallback defaults include this exact `AmbiIntent` block and no `AmbiView`/`AmbiSource` blocks:

```python
"AmbiIntent": {
    "question": "Bagaimana data KPI ini ingin ditampilkan?",
    "options": ["Daftar detail", "Ranking tertinggi", "Dikelompokkan", "Difilter"],
    "default": "Lewati",
},
```

- [ ] **Step 5: Run taxonomy test**

Run: `pytest tests/clarificationMechanism_test.py::test_prd_ambiguity_types_use_ambiintent_not_ambisource -v`

Expected: PASS.

---

### Task 2: Rewrite AmbiSQL prompt

**Files:**
- Modify: `template/promptTemplate.py:278-329`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing prompt test**

Add this test:

```python
def test_ambiguity_prompt_uses_ambisql_question_set_format():
    from template.promptTemplate import build_ambiguity_assessment_prompt

    prompt = build_ambiguity_assessment_prompt(
        user_query="Tampilkan pengguna berdasarkan tanggal registrasi",
        user_role="admin",
        kpi_context="Evidence: Abstain for previous AmbiIntent",
    )

    assert "question_set" in prompt
    assert "has_ambiguity" in prompt
    assert "Question:" in prompt
    assert "Schema:" in prompt
    assert "Evidence:" in prompt
    assert "AmbiIntent" in prompt
    assert "AmbiSource" not in prompt
    assert "Abstain" in prompt
```

- [ ] **Step 2: Run prompt test to verify it fails**

Run: `pytest tests/clarificationMechanism_test.py::test_ambiguity_prompt_uses_ambisql_question_set_format -v`

Expected: FAIL while old prompt still uses `detected_ambiguities` format.

- [ ] **Step 3: Replace prompt implementation**

Replace `build_ambiguity_assessment_prompt()` in `template/promptTemplate.py` with:

```python
def build_ambiguity_assessment_prompt(
    user_query: str,
    user_role: str,
    kpi_context: str = "",
) -> str:
    evidence = kpi_context or "Tidak ada evidence/klarifikasi sebelumnya."
    return f"""## Task
Given a user question, database schema, and optional evidence, identify ambiguities in the user question.
Contents in the evidence are user-provided clarifications to resolve previous detected ambiguities.
The data source for this KPI chatbot is always the database, so do not use AmbiSource.

## Ambiguity Definition & Taxonomy
A user question is ambiguous when there is more than one reasonable interpretation due to unclear, incomplete, or conflicting information.

Level-1 ambiguity types:
- Database-sourced ambiguity: Ambiguity that leads to incorrect or incomplete data retrieval directly from the database due to unclear or underspecified query aspects with respect to schema or content.
- LLM-sourced ambiguity: Ambiguity that causes difficulty applying reasoning beyond direct database retrieval, such as missing context, false assumptions, or underspecified references.

Level-2 ambiguity types:
- AmbiSchema: The question lacks enough context to determine which table or column to use.
- AmbiValue: The question refers to a value that may not match actual database values.
- AmbiIntent: The question lacks keywords clarifying the intended operation, such as ordering, grouping, filtering, ranking, or aggregation.
- AmbiContext: The question lacks adequate information to guide reasoning effectively.
- AmbiFallacy: Assumptions in the question contradict real-world facts or database contents.
- AmbiRef: Spatial or temporal constraints are underspecified and have multiple possible granularities.

## Instructions
1. Analyze user question, database schema, and evidence to identify unresolved ambiguous phrases.
2. For each unresolved ambiguity, assign exactly one level-1 label and one level-2 label.
3. Write a multi-choice question for the user to clarify their intent.
4. Put all concrete answer choices in description.options.
5. If evidence says the user's response to an ambiguity was "Abstain", skip that ambiguity and do not identify it again.
6. If all ambiguities are resolved or the input is unambiguous, return an empty question_set.
7. Do not output AmbiSource.

## Output Format Requirements
You MUST output a strict JSON string:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "string",
      "level_1_label": "Database-sourced ambiguity | LLM-sourced ambiguity",
      "level_2_label": "AmbiSchema | AmbiValue | AmbiIntent | AmbiContext | AmbiFallacy | AmbiRef",
      "description": {{
        "options": ["string"]
      }}
    }}
  ]
}}

## Input
Question: {user_query}
Role: {user_role}
Schema:
{DB_SCHEMA}
Evidence:
{evidence}
--
The ambiguity detection result is:"""
```

- [ ] **Step 4: Run prompt test**

Run: `pytest tests/clarificationMechanism_test.py::test_ambiguity_prompt_uses_ambisql_question_set_format -v`

Expected: PASS.

---

### Task 3: Parse AmbiSQL output into existing detector result

**Files:**
- Modify: `service/ambiguityDetectorService.py:147-193`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing parser tests**

Add these tests:

```python
import pytest


@pytest.mark.asyncio
async def test_detector_maps_ambisql_question_set_to_detected_ambiguities(monkeypatch):
    from service.ambiguityDetectorService import AmbiguityDetectorService

    service = AmbiguityDetectorService()

    async def fake_call_model(**kwargs):
        return '''{
          "has_ambiguity": true,
          "question_set": [
            {
              "question": "Tanggal registrasi ingin digunakan untuk apa?",
              "level_1_label": "Database-sourced ambiguity",
              "level_2_label": "AmbiIntent",
              "description": {
                "options": [
                  "Urutkan berdasarkan tanggal registrasi",
                  "Kelompokkan berdasarkan tanggal registrasi",
                  "Filter berdasarkan tanggal registrasi"
                ]
              }
            }
          ]
        }'''

    monkeypatch.setattr(service.llm, "call_model", fake_call_model)

    result = await service._assess_ambiguity_with_llm(
        "Tampilkan pengguna berdasarkan tanggal registrasi",
        "admin",
        "",
    )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "AmbiIntent"
    assert len(result.detected_ambiguities) == 1
    ambiguity = result.detected_ambiguities[0]
    assert ambiguity.ambiguity_type == "AmbiIntent"
    assert ambiguity.suggested_clarifying_question == "Tanggal registrasi ingin digunakan untuk apa?"
    assert ambiguity.answer_options == [
        "Urutkan berdasarkan tanggal registrasi",
        "Kelompokkan berdasarkan tanggal registrasi",
        "Filter berdasarkan tanggal registrasi",
    ]
    assert ambiguity.metadata["is_ambiguity_level1_type_llm"] is False


@pytest.mark.asyncio
async def test_detector_skips_ambisource_question_set_items(monkeypatch):
    from service.ambiguityDetectorService import AmbiguityDetectorService

    service = AmbiguityDetectorService()

    async def fake_call_model(**kwargs):
        return '''{
          "has_ambiguity": true,
          "question_set": [
            {
              "question": "Should source be DB or LLM?",
              "level_1_label": "LLM-sourced ambiguity",
              "level_2_label": "AmbiSource",
              "description": {"options": ["Database", "LLM"]}
            }
          ]
        }'''

    monkeypatch.setattr(service.llm, "call_model", fake_call_model)

    result = await service._assess_ambiguity_with_llm("query", "admin", "")

    assert result.is_ambiguous is False
    assert result.detected_ambiguities == []
    assert result.ambiguity_type == "none"
```

- [ ] **Step 2: Run parser tests to verify failure**

Run: `pytest tests/clarificationMechanism_test.py::test_detector_maps_ambisql_question_set_to_detected_ambiguities tests/clarificationMechanism_test.py::test_detector_skips_ambisource_question_set_items -v`

Expected: FAIL while parser only understands old `detected_ambiguities` format or accepts unsupported types.

- [ ] **Step 3: Add mapping helpers**

In `service/ambiguityDetectorService.py`, add imports and helper methods inside `AmbiguityDetectorService`:

```python
from schema.clarificationSchema import PRD_AMBIGUITY_TYPES
```

```python
    @staticmethod
    def _is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
        if level_1_label == "LLM-sourced ambiguity":
            return True
        if level_1_label == "Database-sourced ambiguity":
            return False
        return None

    @staticmethod
    def _extract_description_options(description) -> list[str]:
        if not isinstance(description, dict):
            return []
        options = description.get("options", []) or []
        return [str(option).strip() for option in options if str(option).strip()]
```

- [ ] **Step 4: Replace parser body after `result_dict`**

In `_assess_ambiguity_with_llm()`, replace the logic from `ambiguity_score = ...` through the `return AmbiguityAssessmentResult(...)` with:

```python
            question_set = result_dict.get("question_set")
            if isinstance(question_set, list):
                detected_ambiguities = []
                for item in question_set:
                    if not isinstance(item, dict):
                        continue
                    level_2_label = item.get("level_2_label", "none")
                    if level_2_label not in PRD_AMBIGUITY_TYPES or level_2_label == "none":
                        continue

                    options = self._extract_description_options(item.get("description"))
                    is_llm_level_1 = self._is_llm_sourced_level_1(item.get("level_1_label"))
                    detected_ambiguities.append(
                        DetectedAmbiguity(
                            ambiguous_phrase=item.get("ambiguous_phrase"),
                            ambiguity_type=level_2_label,
                            ambiguity_score=0.9,
                            possible_interpretations=[{"text": option} for option in options],
                            suggested_clarifying_question=item.get("question"),
                            answer_options=options,
                            metadata={
                                "is_ambiguity_level1_type_llm": is_llm_level_1,
                            },
                        )
                    )

                is_ambiguous = bool(result_dict.get("has_ambiguity")) and bool(detected_ambiguities)
                primary = detected_ambiguities[0] if detected_ambiguities else None
                return AmbiguityAssessmentResult(
                    ambiguity_score=0.9 if is_ambiguous else 0.0,
                    is_ambiguous=is_ambiguous,
                    ambiguity_type=primary.ambiguity_type if primary else "none",
                    possible_interpretations=primary.possible_interpretations if primary else [],
                    suggested_clarifying_question=primary.suggested_clarifying_question if primary else None,
                    answer_options=primary.answer_options if primary else [],
                    detection_source="llm",
                    detected_ambiguities=detected_ambiguities,
                )
```

Keep the existing legacy `detected_ambiguities` parser below this block as a fallback for old-format LLM responses.

- [ ] **Step 5: Run parser tests**

Run: `pytest tests/clarificationMechanism_test.py::test_detector_maps_ambisql_question_set_to_detected_ambiguities tests/clarificationMechanism_test.py::test_detector_skips_ambisource_question_set_items -v`

Expected: PASS.

---

### Task 4: Persist level-1 source boolean

**Files:**
- Modify: `model/ClarificationQuestion.py:4-6,20-24`
- Modify: `repository/clarificationRepository.py:13-38`
- Modify: `service/clarificationService.py:122-133`
- Create: `alembic/versions/<revision>_add_clarification_question_level1_source.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing repository/model test**

Add this test:

```python
def test_clarification_question_has_level1_source_column():
    from model.ClarificationQuestion import ClarificationQuestion

    column = ClarificationQuestion.__table__.columns.get("is_ambiguity_level1_type_llm")

    assert column is not None
    assert column.nullable is True
```

- [ ] **Step 2: Run model test to verify failure**

Run: `pytest tests/clarificationMechanism_test.py::test_clarification_question_has_level1_source_column -v`

Expected: FAIL until the ORM column exists.

- [ ] **Step 3: Add ORM column**

In `model/ClarificationQuestion.py`, update imports:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
```

Add this column after `ambiguity_type`:

```python
    is_ambiguity_level1_type_llm: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
```

- [ ] **Step 4: Accept and store repository field**

In `repository/clarificationRepository.py`, add parameter to `create()` after `decision_source`:

```python
        is_ambiguity_level1_type_llm: bool | None = None,
```

Add it to `ClarificationQuestion(...)`:

```python
            is_ambiguity_level1_type_llm=is_ambiguity_level1_type_llm,
```

- [ ] **Step 5: Pass metadata from clarification service**

In `service/clarificationService.py`, update the clarify-path `self.repo.create(...)` call to include:

```python
                is_ambiguity_level1_type_llm=ambiguity.metadata.get("is_ambiguity_level1_type_llm"),
```

Do not add this to direct-path create unless direct-path ambiguity metadata is available.

- [ ] **Step 6: Create migration**

Create a new Alembic migration file with a unique revision id, for example `alembic/versions/7a4c2e9b1f03_add_clarification_question_level1_source.py`:

```python
"""add clarification question level1 source

Revision ID: 7a4c2e9b1f03
Revises: c0be990ab6d9
Create Date: 2026-05-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7a4c2e9b1f03"
down_revision: Union[str, None] = "c0be990ab6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("is_ambiguity_level1_type_llm", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clarification_questions", "is_ambiguity_level1_type_llm")
```

If the current Alembic head differs when implementing, set `down_revision` to the actual current head from `alembic heads`.

- [ ] **Step 7: Run model test**

Run: `pytest tests/clarificationMechanism_test.py::test_clarification_question_has_level1_source_column -v`

Expected: PASS.

---

### Task 5: Verify detector/CQ separation and full clarification flow

**Files:**
- Modify: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Add separation test**

Add this test:

```python
@pytest.mark.asyncio
async def test_detector_passes_raw_options_without_normalizing_cq_defaults(monkeypatch):
    from service.ambiguityDetectorService import AmbiguityDetectorService

    service = AmbiguityDetectorService()

    async def fake_call_model(**kwargs):
        return '''{
          "has_ambiguity": true,
          "question_set": [
            {
              "question": "Metrik mana yang dimaksud?",
              "level_1_label": "Database-sourced ambiguity",
              "level_2_label": "AmbiSchema",
              "description": {
                "options": ["kpi_master_records::target", "kpi_tracker_records::realisasi"]
              }
            }
          ]
        }'''

    monkeypatch.setattr(service.llm, "call_model", fake_call_model)

    result = await service._assess_ambiguity_with_llm("KPI terbaik", "admin", "")

    assert result.answer_options == [
        "kpi_master_records::target",
        "kpi_tracker_records::realisasi",
    ]
    assert "Lewati" not in result.answer_options
    assert "Lainnya" not in result.answer_options
```

- [ ] **Step 2: Run separation test**

Run: `pytest tests/clarificationMechanism_test.py::test_detector_passes_raw_options_without_normalizing_cq_defaults -v`

Expected: PASS after Task 3. This proves detector does not perform final CQ option normalization.

- [ ] **Step 3: Run all clarification tests**

Run: `pytest tests/clarificationMechanism_test.py -v`

Expected: PASS.

---

### Task 6: Final validation

**Files:**
- No code changes unless validation exposes a defect.

- [ ] **Step 1: Run targeted streaming/chat tests**

Run: `pytest tests/clarificationMechanism_test.py tests/chatStreaming_test.py -v`

Expected: PASS.

- [ ] **Step 2: Run migration history check**

Run: `alembic heads`

Expected: single intended head. If multiple heads are expected because this branch already contains a merge migration, verify the new migration descends from the merge head.

- [ ] **Step 3: Review git diff**

Run: `git diff -- schema/clarificationSchema.py template/promptTemplate.py service/ambiguityDetectorService.py service/clarificationQuestionGeneratorService.py service/clarificationService.py repository/clarificationRepository.py model/ClarificationQuestion.py alembic/versions tests/clarificationMechanism_test.py`

Expected: Diff only includes AmbiSQL prompt/parser mapping, level-1 source persistence, and tests.

---

## Self-Review Notes

- Spec coverage: prompt rewrite is Task 2; compatible parser is Task 3; CQ separation is Tasks 3 and 5; DB column/migration is Task 4; tests are Tasks 1-6.
- No `AmbiSource` implementation is planned; tests assert it is skipped/not listed.
- The plan keeps API response shape unchanged and stores level-1 source as boolean metadata plus DB column.
