# Service Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor chat, clarification, ambiguity detection, and graphic services into cleaner, smaller, testable units without changing public behavior.

**Architecture:** Keep the four tagged services as public entry points. Extract typed chat pipeline state, chat response formatting, clarification pure helpers, ambiguity parsing/normalization, and graphic constants into focused helper modules. Add focused tests for pure helpers and run existing chat/clarification/graphic regressions.

**Tech Stack:** Python 3.10, FastAPI, SQLAlchemy async, Pydantic, pytest, pandas, matplotlib.

---

## File Structure

Create:

- `service/chatPipelineTypes.py` — typed `ChatPipelineContext` dataclass replacing repeated pipeline dictionary key mutation.
- `service/chatResponseBuilder.py` — message/payload helpers for chat responses and graphics persistence payloads.
- `service/clarificationHelpers.py` — pure clarification helper functions for effective answers, QA pairs, session merge, repeated-question filtering, and fallback disambiguation.
- `service/ambiguityParsing.py` — pure ambiguity parser/normalizer functions for fenced JSON, AmbiSQL `question_set`, legacy payloads, and fallback results.
- `service/graphicConstants.py` — chart type, hint, color, threshold, month-label constants.
- `tests/ambiguityParsing_test.py` — focused parser/normalizer tests.
- `tests/clarificationHelpers_test.py` — focused clarification helper tests.
- `tests/chatResponseBuilder_test.py` — focused response builder tests.

Modify:

- `service/chatService.py` — use typed context and response builder; reduce long `process_query()` and magic keys.
- `service/clarificationService.py` — use clarification helpers; remove duplicate logic and comments that describe what code already does.
- `service/ambiguityDetectorService.py` — use ambiguity parsing helpers; keep LLM-only detector flow.
- `service/graphicService.py` — use graphic constants; reduce magic strings and comments while preserving public API.

---

### Task 1: Add ambiguity parsing helper with tests

**Files:**
- Create: `service/ambiguityParsing.py`
- Create: `tests/ambiguityParsing_test.py`
- Modify: none

- [ ] **Step 1: Write failing tests**

Create `tests/ambiguityParsing_test.py`:

```python
import json

import pytest

from service.ambiguityParsing import (
    build_non_ambiguous_result,
    normalize_ambiguity_payload,
    parse_llm_json_response,
)


def test_parse_llm_json_response_handles_fenced_json():
    payload = {"has_ambiguity": False, "question_set": []}
    response = f"```json\n{json.dumps(payload)}\n```"

    assert parse_llm_json_response(response) == payload


def test_parse_llm_json_response_handles_wrapper_text():
    response = 'Here is JSON: {"is_ambiguous": true, "answer_options": ["A"]}'

    assert parse_llm_json_response(response) == {
        "is_ambiguous": True,
        "answer_options": ["A"],
    }


def test_parse_llm_json_response_rejects_empty_response():
    with pytest.raises(json.JSONDecodeError):
        parse_llm_json_response("")


def test_normalize_ambiguity_payload_handles_question_set():
    result = normalize_ambiguity_payload(
        {
            "has_ambiguity": True,
            "question_set": [
                {
                    "level_1_label": "LLM-sourced ambiguity",
                    "level_2_label": "time_scope",
                    "question": "Periode mana yang dimaksud?",
                    "description": {"options": ["2024", "2025"]},
                }
            ],
        }
    )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "time_scope"
    assert result.answer_options == ["2024", "2025"]
    assert len(result.detected_ambiguities) == 1
    assert result.detected_ambiguities[0].metadata["is_ambiguity_level1_type_llm"] is True


def test_normalize_ambiguity_payload_handles_legacy_payload():
    result = normalize_ambiguity_payload(
        {
            "is_ambiguous": True,
            "detected_ambiguities": [
                {
                    "ambiguity_type": "metric_scope",
                    "possible_interpretations": [{"text": "Revenue"}],
                    "suggested_clarifying_question": "KPI mana?",
                    "answer_options": ["Revenue", "Cost"],
                }
            ],
        }
    )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "metric_scope"
    assert result.suggested_clarifying_question == "KPI mana?"
    assert result.answer_options == ["Revenue", "Cost"]


def test_build_non_ambiguous_result_returns_safe_fallback():
    result = build_non_ambiguous_result(detection_source="llm_fallback")

    assert result.is_ambiguous is False
    assert result.ambiguity_type == "none"
    assert result.possible_interpretations == []
    assert result.answer_options == []
    assert result.detected_ambiguities == []
    assert result.detection_source == "llm_fallback"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/ambiguityParsing_test.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'service.ambiguityParsing'`.

- [ ] **Step 3: Implement helper**

Create `service/ambiguityParsing.py`:

```python
import json
import re
from typing import Any

from schema.clarificationSchema import AmbiguityAssessmentResult, DetectedAmbiguity


def parse_llm_json_response(response: str) -> dict[str, Any]:
    cleaned = (response or "").strip()
    if not cleaned:
        raise json.JSONDecodeError("Empty response", response or "", 0)

    if cleaned.startswith("```"):
        cleaned = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        ).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*}", cleaned)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("JSON root must be object", cleaned, 0)
    return parsed


def build_non_ambiguous_result(detection_source: str = "llm") -> AmbiguityAssessmentResult:
    return AmbiguityAssessmentResult(
        is_ambiguous=False,
        ambiguity_type="none",
        possible_interpretations=[],
        suggested_clarifying_question=None,
        answer_options=[],
        detection_source=detection_source,
        detected_ambiguities=[],
    )


def normalize_ambiguity_payload(payload: dict[str, Any]) -> AmbiguityAssessmentResult:
    question_set = payload.get("question_set")
    if isinstance(question_set, list):
        return _normalize_question_set(payload, question_set)
    return _normalize_legacy_payload(payload)


def _normalize_question_set(payload: dict[str, Any], question_set: list[Any]) -> AmbiguityAssessmentResult:
    detected_ambiguities = [
        ambiguity
        for item in question_set
        if isinstance(item, dict)
        for ambiguity in [_build_question_set_ambiguity(item)]
        if ambiguity is not None
    ]

    if not detected_ambiguities:
        return build_non_ambiguous_result()

    is_ambiguous = bool(payload.get("has_ambiguity", False)) and bool(detected_ambiguities)
    primary = detected_ambiguities[0]
    return AmbiguityAssessmentResult(
        is_ambiguous=is_ambiguous,
        ambiguity_type=primary.ambiguity_type,
        possible_interpretations=primary.possible_interpretations,
        suggested_clarifying_question=primary.suggested_clarifying_question,
        answer_options=primary.answer_options,
        detection_source="llm",
        detected_ambiguities=detected_ambiguities,
        is_ambiguous_level1_type_llm=primary.metadata.get("is_ambiguity_level1_type_llm"),
    )


def _build_question_set_ambiguity(item: dict[str, Any]) -> DetectedAmbiguity | None:
    options = extract_description_options(item.get("description", {}))
    if not options:
        return None

    level_1_label = item.get("level_1_label")
    return DetectedAmbiguity(
        ambiguity_type=str(item.get("level_2_label")),
        possible_interpretations=[{"text": option} for option in options],
        suggested_clarifying_question=item.get("question"),
        answer_options=options,
        metadata={
            "is_ambiguity_level1_type_llm": is_llm_sourced_level_1(level_1_label),
            "level_1_label": level_1_label,
        },
    )


def _normalize_legacy_payload(payload: dict[str, Any]) -> AmbiguityAssessmentResult:
    detected_ambiguities = _build_legacy_detected_ambiguities(payload)
    is_ambiguous = bool(payload.get("is_ambiguous", bool(detected_ambiguities))) and bool(
        detected_ambiguities or payload.get("answer_options")
    )
    primary = detected_ambiguities[0] if detected_ambiguities else None

    return AmbiguityAssessmentResult(
        is_ambiguous=is_ambiguous,
        ambiguity_type=primary.ambiguity_type if primary else payload.get("ambiguity_type", "none"),
        possible_interpretations=(
            primary.possible_interpretations
            if primary
            else payload.get("possible_interpretations", []) or []
        ),
        suggested_clarifying_question=(
            primary.suggested_clarifying_question
            if primary
            else payload.get("suggested_clarifying_question")
        ),
        answer_options=primary.answer_options if primary else payload.get("answer_options", []) or [],
        detection_source="llm",
        detected_ambiguities=detected_ambiguities,
    )


def _build_legacy_detected_ambiguities(payload: dict[str, Any]) -> list[DetectedAmbiguity]:
    detected_items = payload.get("detected_ambiguities", []) or []
    detected_ambiguities = [
        DetectedAmbiguity(
            ambiguity_type=item.get("ambiguity_type", "none"),
            possible_interpretations=item.get("possible_interpretations", []) or [],
            suggested_clarifying_question=item.get("suggested_clarifying_question"),
            answer_options=item.get("answer_options") or item.get("suggested_options", []) or [],
            metadata=item.get("metadata", {}) or {},
        )
        for item in detected_items
        if isinstance(item, dict)
    ]

    if detected_ambiguities:
        return detected_ambiguities

    interpretations = payload.get("possible_interpretations", [])
    possible_interpretations = _normalize_possible_interpretations(interpretations)
    if payload.get("ambiguity_type", "none") == "none":
        return []

    return [
        DetectedAmbiguity(
            ambiguity_type=payload.get("ambiguity_type", "none"),
            possible_interpretations=possible_interpretations,
            suggested_clarifying_question=payload.get("suggested_clarifying_question"),
            answer_options=payload.get("answer_options") or payload.get("suggested_options", []) or [],
        )
    ]


def _normalize_possible_interpretations(interpretations: Any) -> list[Any]:
    if interpretations and isinstance(interpretations[0], str):
        return [{"text": interpretation} for interpretation in interpretations]
    return interpretations or []


def is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
    if not level_1_label:
        return None
    label_lower = level_1_label.lower()
    if "llm-sourced" in label_lower or "llm sourced" in label_lower:
        return True
    if "database-sourced" in label_lower or "database sourced" in label_lower:
        return False
    return None


def extract_description_options(description: Any) -> list[str]:
    if isinstance(description, dict) and "options" in description:
        options = description["options"]
        if isinstance(options, list):
            return [str(option) for option in options]
    return []
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/ambiguityParsing_test.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/ambiguityParsing.py tests/ambiguityParsing_test.py
git commit -m "refactor: extract ambiguity parsing helpers"
```

---

### Task 2: Wire ambiguity detector to parsing helper

**Files:**
- Modify: `service/ambiguityDetectorService.py`
- Test: `tests/ambiguityParsing_test.py`

- [ ] **Step 1: Refactor imports and detector flow**

In `service/ambiguityDetectorService.py`, remove imports no longer needed by this file:

```python
import json
import re

from schema.clarificationSchema import (
    AmbiguityAssessmentResult,
    DetectedAmbiguity,
    PRD_AMBIGUITY_TYPES,
)
```

Replace with:

```python
import json
import logging

from schema.clarificationSchema import AmbiguityAssessmentResult
from service.ambiguityParsing import (
    build_non_ambiguous_result,
    normalize_ambiguity_payload,
    parse_llm_json_response,
)
```

Keep `json` only because `json.JSONDecodeError` is still caught.

- [ ] **Step 2: Replace fallback construction**

In `detect_ambiguity()`, replace manual fallback `AmbiguityAssessmentResult(...)` with:

```python
return build_non_ambiguous_result(detection_source="llm_fallback")
```

- [ ] **Step 3: Replace static parser wrapper bodies**

Keep these static methods for compatibility if anything imports them directly, but delegate:

```python
@staticmethod
def _parse_llm_json_response(response: str) -> dict:
    return parse_llm_json_response(response)

@staticmethod
def _is_llm_sourced_level_1(level_1_label: str | None) -> bool | None:
    from service.ambiguityParsing import is_llm_sourced_level_1

    return is_llm_sourced_level_1(level_1_label)

@staticmethod
def _extract_description_options(description) -> list[str]:
    from service.ambiguityParsing import extract_description_options

    return extract_description_options(description)
```

- [ ] **Step 4: Shorten `_assess_ambiguity_with_llm()`**

Replace parsing and normalization block after `response = await self.llm.call_model(...)` with:

```python
result_dict = parse_llm_json_response(response)
return normalize_ambiguity_payload(result_dict)
```

The method should still catch `json.JSONDecodeError` and generic `Exception` exactly as before.

- [ ] **Step 5: Run parser tests**

Run:

```bash
pytest tests/ambiguityParsing_test.py -v
```

Expected: PASS.

- [ ] **Step 6: Run clarification regression tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service/ambiguityDetectorService.py
git commit -m "refactor: simplify ambiguity detector flow"
```

---

### Task 3: Add clarification helper with tests

**Files:**
- Create: `service/clarificationHelpers.py`
- Create: `tests/clarificationHelpers_test.py`
- Modify: none

- [ ] **Step 1: Write failing tests**

Create `tests/clarificationHelpers_test.py`:

```python
from types import SimpleNamespace
from uuid import uuid4

from schema.clarificationSchema import ClarificationAnswerItem
from service.clarificationHelpers import (
    build_fallback_disambiguated_query,
    build_qa_set,
    build_session_qa_set,
    effective_answer,
    filter_unanswered_ambiguities,
)


def make_answer(question_id, selected_option, free_text=None):
    return ClarificationAnswerItem(
        question_id=question_id,
        selected_option=selected_option,
        free_text=free_text,
    )


def test_effective_answer_uses_free_text_for_lainnya():
    answer = make_answer(uuid4(), "Lainnya", "periode Q1")

    assert effective_answer(answer) == "periode Q1"


def test_effective_answer_uses_selected_option_when_not_lainnya():
    answer = make_answer(uuid4(), "2025", "ignored")

    assert effective_answer(answer) == "2025"


def test_build_qa_set_uses_log_question_and_answer():
    question_id = uuid4()
    answer = make_answer(question_id, "2025")
    log = SimpleNamespace(
        ambiguity_type="time_scope",
        clarification_question="Periode mana?",
    )

    pairs = build_qa_set([answer], {str(question_id): log})

    assert len(pairs) == 1
    assert pairs[0].level1 == "time_scope"
    assert pairs[0].question == "Periode mana?"
    assert pairs[0].answer == "2025"


def test_build_session_qa_set_current_answers_override_history():
    question_id = uuid4()
    logs = [
        SimpleNamespace(
            clarification_question="Periode mana?",
            selected_answer="2024",
            ambiguity_type="time_scope",
        )
    ]
    current_pairs = build_qa_set(
        [make_answer(question_id, "2025")],
        {
            str(question_id): SimpleNamespace(
                ambiguity_type="time_scope",
                clarification_question="Periode mana?",
            )
        },
    )

    pairs = build_session_qa_set(logs, current_pairs)

    assert len(pairs) == 1
    assert pairs[0].answer == "2025"


def test_filter_unanswered_ambiguities_removes_answered_questions():
    ambiguities = [
        SimpleNamespace(suggested_clarifying_question="Periode mana?"),
        SimpleNamespace(suggested_clarifying_question="KPI mana?"),
    ]
    answered_questions = {"periode mana?"}

    filtered = filter_unanswered_ambiguities(ambiguities, answered_questions)

    assert [item.suggested_clarifying_question for item in filtered] == ["KPI mana?"]


def test_build_fallback_disambiguated_query_combines_answers_and_constraints():
    answers = [
        make_answer(uuid4(), "Lewati"),
        make_answer(uuid4(), "Lainnya", "periode Q1"),
        make_answer(uuid4(), "Revenue"),
    ]

    result = build_fallback_disambiguated_query(
        "Tampilkan KPI",
        answers,
        additional_constraints="divisi sales",
    )

    assert result == "Tampilkan KPI (periode Q1; Revenue; divisi sales)"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationHelpers_test.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'service.clarificationHelpers'`.

- [ ] **Step 3: Implement helper**

Create `service/clarificationHelpers.py`:

```python
from collections.abc import Mapping, Sequence
from typing import Any

from schema.clarificationSchema import ClarificationAnswerItem
from service.preferenceTreeService import QAPair

SKIP_OPTION = "Lewati"
FREE_TEXT_OPTION = "Lainnya"
UNKNOWN_AMBIGUITY_TYPE = "unknown"


def effective_answer(answer: ClarificationAnswerItem) -> str:
    if answer.selected_option == FREE_TEXT_OPTION and answer.free_text:
        return answer.free_text
    return answer.selected_option


def question_key(question: str) -> str:
    return question.strip().casefold()


def build_qa_set(
    clarification_answers: list[ClarificationAnswerItem],
    log_by_id: Mapping[str, object],
) -> list[QAPair]:
    return [
        QAPair(
            level1=getattr(log_by_id[str(answer.question_id)], "ambiguity_type", None)
            or UNKNOWN_AMBIGUITY_TYPE,
            level2=getattr(log_by_id[str(answer.question_id)], "clarification_question", None)
            or answer.question_id,
            question=getattr(log_by_id[str(answer.question_id)], "clarification_question", None)
            or answer.question_id,
            answer=effective_answer(answer),
        )
        for answer in clarification_answers
    ]


def build_session_qa_set(logs: list[object], current_qa_set: list[QAPair]) -> list[QAPair]:
    current_by_question = {question_key(pair.question): pair for pair in current_qa_set}
    session_pairs: list[QAPair] = []
    seen_questions: set[str] = set()

    for log in reversed(logs):
        question = (getattr(log, "clarification_question", None) or "").strip()
        if not question:
            continue

        key = question.casefold()
        pair = current_by_question.get(key) or _qa_pair_from_answered_log(log, question)
        if pair is None or key in seen_questions:
            continue

        session_pairs.append(pair)
        seen_questions.add(key)

    for pair in current_qa_set:
        key = question_key(pair.question)
        if key not in seen_questions:
            session_pairs.append(pair)
            seen_questions.add(key)

    return session_pairs


def _qa_pair_from_answered_log(log: object, question: str) -> QAPair | None:
    selected_answer = getattr(log, "selected_answer", None)
    if selected_answer is None:
        return None
    return QAPair(
        level1=getattr(log, "ambiguity_type", None) or UNKNOWN_AMBIGUITY_TYPE,
        level2=question,
        question=question,
        answer=str(selected_answer),
    )


def answered_question_keys(qa_set: list[QAPair]) -> set[str]:
    return {question_key(pair.question) for pair in qa_set}


def filter_unanswered_ambiguities(
    ambiguities: Sequence[Any],
    answered_questions: set[str],
) -> list[Any]:
    return [
        ambiguity
        for ambiguity in ambiguities
        if question_key(getattr(ambiguity, "suggested_clarifying_question", None) or "")
        not in answered_questions
    ]


def build_fallback_disambiguated_query(
    original_query: str,
    clarification_answers: list[ClarificationAnswerItem],
    additional_constraints: str | None = None,
) -> str:
    query = original_query.strip()
    additions = [
        value
        for answer in clarification_answers
        if answer.selected_option != SKIP_OPTION
        for value in [_answer_addition(answer)]
        if value
    ]

    if additional_constraints:
        additions.append(additional_constraints.strip())

    if not additions:
        return query
    return f"{query} ({'; '.join(additions)})"


def _answer_addition(answer: ClarificationAnswerItem) -> str:
    if answer.selected_option == FREE_TEXT_OPTION and answer.free_text:
        return answer.free_text.strip()
    return answer.selected_option.strip()
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/clarificationHelpers_test.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/clarificationHelpers.py tests/clarificationHelpers_test.py
git commit -m "refactor: extract clarification helpers"
```

---

### Task 4: Wire clarification service to helpers

**Files:**
- Modify: `service/clarificationService.py`
- Test: `tests/clarificationHelpers_test.py`, `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Update imports**

In `service/clarificationService.py`, remove:

```python
from collections.abc import Mapping
```

Add:

```python
from service.clarificationHelpers import (
    answered_question_keys,
    build_fallback_disambiguated_query,
    build_qa_set,
    build_session_qa_set,
    effective_answer,
    filter_unanswered_ambiguities,
)
```

Keep `QAPair` import only if type annotations still use it; otherwise remove it.

- [ ] **Step 2: Delegate `_effective_answer()`**

Replace body with:

```python
@staticmethod
def _effective_answer(answer: ClarificationAnswerItem) -> str:
    return effective_answer(answer)
```

- [ ] **Step 3: Delegate QA helpers**

Replace `_build_qa_set()` with:

```python
@staticmethod
def _build_qa_set(
    clarification_answers: list[ClarificationAnswerItem],
    log_by_id,
) -> list[QAPair]:
    return build_qa_set(clarification_answers, log_by_id)
```

Replace `_build_session_qa_set()` with:

```python
@staticmethod
def _build_session_qa_set(logs: list[object], current_qa_set: list[QAPair]) -> list[QAPair]:
    return build_session_qa_set(logs, current_qa_set)
```

- [ ] **Step 4: Use repeated-question filter helper**

Replace this block in `handle_clarification_response()`:

```python
answered_questions = {pair.question.strip().casefold() for pair in session_qa_set}
recheck_result.detected_ambiguities = [
    ambiguity
    for ambiguity in recheck_result.detected_ambiguities
    if (ambiguity.suggested_clarifying_question or "").strip().casefold()
    not in answered_questions
]
```

With:

```python
recheck_result.detected_ambiguities = filter_unanswered_ambiguities(
    recheck_result.detected_ambiguities,
    answered_question_keys(session_qa_set),
)
```

- [ ] **Step 5: Delegate fallback builder**

Replace `_build_fallback_disambiguated_query()` body with:

```python
return build_fallback_disambiguated_query(
    original_query,
    clarification_answers,
    additional_constraints,
)
```

- [ ] **Step 6: Remove stale comments**

Delete comments that only describe direct code steps, including:

```python
# Build current QA set from submitted answers only
# Build full session QA set including all answered logs + current answers
# Process logs in reverse order (most recent first)
# If current answer exists for this question, use it
# Otherwise, use log's answer if it exists
# Skip if we've already seen this question
# Add any current answers that weren't in logs
# Response adalah langsung disambiguated query (bukan JSON)
# Fallback strategy: Gunakan smart combination tanpa LLM
```

Keep comments only if they explain why a fallback exists.

- [ ] **Step 7: Run focused helper tests**

Run:

```bash
pytest tests/clarificationHelpers_test.py -v
```

Expected: PASS.

- [ ] **Step 8: Run clarification regression tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add service/clarificationService.py
git commit -m "refactor: simplify clarification service helpers"
```

---

### Task 5: Add chat pipeline types and response builder with tests

**Files:**
- Create: `service/chatPipelineTypes.py`
- Create: `service/chatResponseBuilder.py`
- Create: `tests/chatResponseBuilder_test.py`
- Modify: none

- [ ] **Step 1: Write failing response builder tests**

Create `tests/chatResponseBuilder_test.py`:

```python
from types import SimpleNamespace
from uuid import uuid4

from schema.chatSchema import ChatResponse
from service.chatResponseBuilder import (
    AI_UNAVAILABLE_MESSAGE,
    SECURITY_BLOCKED_MESSAGE,
    build_ai_unavailable_response,
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)


def test_build_clarification_prompt_message_includes_user_query_and_questions():
    questions = [
        SimpleNamespace(question="Periode mana?"),
        SimpleNamespace(question="KPI mana?"),
    ]

    message = build_clarification_prompt_message("Tampilkan KPI", questions)

    assert message == (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait 'Tampilkan KPI', "
        "silakan jawab pertanyaan berikut.\n"
        "1. Periode mana?\n"
        "2. KPI mana?"
    )


def test_build_graphics_payload_returns_none_for_empty_results():
    assert build_graphics_payload([]) is None


def test_build_graphics_payload_normalizes_empty_kpi_name():
    result = SimpleNamespace(kpi_name="", chart_type="bar", image_url="/public/a.png")

    assert build_graphics_payload([result]) == [
        {"kpi_name": None, "chart_type": "bar", "image_url": "/public/a.png"}
    ]


def test_build_security_blocked_response_uses_safe_message():
    session_id = uuid4()
    response = build_security_blocked_response(session_id=session_id, pipeline_stages=[])

    assert isinstance(response, ChatResponse)
    assert response.session_id == session_id
    assert response.message == SECURITY_BLOCKED_MESSAGE


def test_build_ai_unavailable_response_uses_safe_message():
    session_id = uuid4()
    response = build_ai_unavailable_response(session_id=session_id, pipeline_stages=[])

    assert response.session_id == session_id
    assert response.message == AI_UNAVAILABLE_MESSAGE
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/chatResponseBuilder_test.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'service.chatResponseBuilder'`.

- [ ] **Step 3: Implement pipeline context**

Create `service/chatPipelineTypes.py`:

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass
class ChatPipelineContext:
    session_id: UUID
    user_id: UUID
    user_role: str
    user_query: str
    generated_sql: str | None = None
    wireguard_status: str | None = None
    wireguard_reason: str | None = None
    execution_status: str | None = None
    rows_returned: int | None = None
    execution_time_ms: int | None = None
```

- [ ] **Step 4: Implement response builder**

Create `service/chatResponseBuilder.py`:

```python
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from schema.chatSchema import ChatResponse, PipelineStageInfo

AI_UNAVAILABLE_MESSAGE = "Layanan AI sementara tidak tersedia. Silakan coba lagi."
SECURITY_BLOCKED_MESSAGE = (
    "Permintaan Anda tidak dapat diproses karena alasan keamanan. "
    "Silakan ajukan pertanyaan yang berbeda tentang data KPI."
)


def build_clarification_prompt_message(user_message: str, questions: Sequence[Any]) -> str:
    question_text = "\n".join(
        f"{index + 1}. {question.question}" for index, question in enumerate(questions)
    )
    suffix = f"\n{question_text}" if question_text else ""
    return (
        "Terdapat beberapa pertanyaan yang ingin saya tanyakan terkait "
        f"'{user_message}', silakan jawab pertanyaan berikut."
        f"{suffix}"
    )


def build_graphics_payload(graphic_results: Sequence[Any]) -> list[dict[str, str | None]] | None:
    payload = [
        {
            "kpi_name": result.kpi_name or None,
            "chart_type": result.chart_type,
            "image_url": result.image_url,
        }
        for result in graphic_results
    ]
    return payload or None


def build_security_blocked_response(
    session_id: UUID,
    pipeline_stages: list[PipelineStageInfo],
) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message=SECURITY_BLOCKED_MESSAGE,
        pipeline_stages=pipeline_stages,
    )


def build_ai_unavailable_response(
    session_id: UUID,
    pipeline_stages: list[PipelineStageInfo],
) -> ChatResponse:
    return ChatResponse(
        session_id=session_id,
        message=AI_UNAVAILABLE_MESSAGE,
        pipeline_stages=pipeline_stages,
    )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest tests/chatResponseBuilder_test.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add service/chatPipelineTypes.py service/chatResponseBuilder.py tests/chatResponseBuilder_test.py
git commit -m "refactor: add chat pipeline helpers"
```

---

### Task 6: Wire chat service to typed context and response builder

**Files:**
- Modify: `service/chatService.py`
- Test: `tests/chatResponseBuilder_test.py`, `tests/chatPipeline_test.py`

- [ ] **Step 1: Update imports and logger**

In `service/chatService.py`, add:

```python
from service.chatPipelineTypes import ChatPipelineContext
from service.chatResponseBuilder import (
    build_ai_unavailable_response,
    build_clarification_prompt_message,
    build_graphics_payload,
    build_security_blocked_response,
)
```

Add below settings:

```python
logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Replace `_build_pipeline_context()`**

Replace return type and body:

```python
@staticmethod
def _build_pipeline_context(
    session_id: UUID,
    user_id: UUID,
    user_role: str,
    user_message: str,
) -> ChatPipelineContext:
    return ChatPipelineContext(
        session_id=session_id,
        user_id=user_id,
        user_role=user_role,
        user_query=user_message,
    )
```

- [ ] **Step 3: Update context type hints**

Change helper signatures from `pipeline: dict[str, Any]` to `pipeline: ChatPipelineContext` for:

```python
_run_nl_to_sql_stage
_run_sql_validation_stage
_run_sql_execution_stage
_handle_pipeline_error
```

Keep `Any` import if still needed for `context_from_clarification`.

- [ ] **Step 4: Replace context dictionary mutation**

Replace:

```python
pipeline["execution_status"] = "degraded"
pipeline["generated_sql"] = generated_sql
pipeline["wireguard_status"] = "PASS" if validation.is_valid else "FAIL"
pipeline["wireguard_reason"] = validation.reason
pipeline["execution_status"] = "success"
pipeline["rows_returned"] = rows_count
pipeline["execution_time_ms"] = exec_ms
pipeline["execution_status"] = "error"
```

With:

```python
pipeline.execution_status = "degraded"
pipeline.generated_sql = generated_sql
pipeline.wireguard_status = "PASS" if validation.is_valid else "FAIL"
pipeline.wireguard_reason = validation.reason
pipeline.execution_status = "success"
pipeline.rows_returned = rows_count
pipeline.execution_time_ms = exec_ms
pipeline.execution_status = "error"
```

- [ ] **Step 5: Use response builder for clarification message**

Replace inline `query_message = (...)` in clarification early return with:

```python
query_message = build_clarification_prompt_message(
    user_message,
    clarification_response.questions,
)
```

- [ ] **Step 6: Use AI unavailable response builder**

Replace:

```python
return ChatResponse(
    session_id=session_id,
    message="Layanan AI sementara tidak tersedia. Silakan coba lagi.",
    pipeline_stages=stages,
)
```

With:

```python
return build_ai_unavailable_response(session_id=session_id, pipeline_stages=stages)
```

- [ ] **Step 7: Use security blocked response builder**

Replace guardrail invalid return with:

```python
return build_security_blocked_response(session_id=session_id, pipeline_stages=stages)
```

- [ ] **Step 8: Use graphics payload builder**

Replace:

```python
graphics_payload = [
    {"kpi_name": r.kpi_name or None, "chart_type": r.chart_type, "image_url": r.image_url}
    for r in graphic_results
] or None
```

With:

```python
graphics_payload = build_graphics_payload(graphic_results)
```

- [ ] **Step 9: Replace root logging calls**

Replace:

```python
logging.error("user_message: " + user_message + "")
logging.error(f"Generated SQL: {generated_sql}")
logging.info(
    f"Menjalankan SQL untuk user_id={user_id} role={user_role}: {sanitized_sql}"
)
logging.error(f"Error server saat memproses query: {error}")
logging.error(f"Error tidak terduga dalam memproses query: {error}")
logging.error(f"Error saat mengeksekusi SQL: {e}")
```

With:

```python
logger.info("Generated SQL for user_id=%s role=%s", user_id, user_role)
logger.info(
    "Menjalankan SQL untuk user_id=%s role=%s: %s",
    user_id,
    user_role,
    sanitized_sql,
)
logger.error("Error server saat memproses query: %s", error)
logger.error("Error tidak terduga dalam memproses query: %s", error)
logger.error("Error saat mengeksekusi SQL: %s", e)
```

Remove raw user-message logging.

- [ ] **Step 10: Remove stale comments/docstrings**

Remove module docstring and comments that only enumerate stages already visible in method names. Keep user-safe error text unchanged.

- [ ] **Step 11: Run focused tests**

Run:

```bash
pytest tests/chatResponseBuilder_test.py -v
```

Expected: PASS.

- [ ] **Step 12: Run chat regression tests**

Run:

```bash
pytest tests/chatPipeline_test.py -v
```

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add service/chatService.py
git commit -m "refactor: simplify chat pipeline orchestration"
```

---

### Task 7: Extract graphic constants and clean graphic service

**Files:**
- Create: `service/graphicConstants.py`
- Modify: `service/graphicService.py`
- Test: `tests/graphicService_test.py`

- [ ] **Step 1: Create constants module**

Create `service/graphicConstants.py`:

```python
import re

SUPPORTED_CHART_TYPES = {
    "bar",
    "pie",
    "donut",
    "line",
    "grouped_bar",
    "stacked_bar",
    "progress",
    "trl_progress",
}

VALUE_COLUMN_HINTS = (
    "total",
    "jumlah",
    "sum",
    "avg",
    "average",
    "rata",
    "nilai",
    "score",
    "persen",
    "percentage",
    "realisasi",
    "count",
    "qty",
    "value",
    "actual",
    "pencapaian",
)
TARGET_COLUMN_HINTS = ("target", "goal", "sasaran")
CATEGORY_COLUMN_HINTS = (
    "bulan",
    "month",
    "tanggal",
    "date",
    "periode",
    "nama",
    "kpi",
    "divisi",
    "kategori",
    "category",
    "label",
)
MONTH_COLUMN_HINTS = ("bulan", "bulan_num", "month", "month_num")
KPI_COLUMN_HINTS = ("kpi", "nama", "kategori", "category", "produk", "product", "name", "indikator")
NOTES_HINTS = ("note", "notes", "keterangan", "catatan", "deskripsi", "description")

MONTH_LABELS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "Mei",
    6: "Jun",
    7: "Jul",
    8: "Agu",
    9: "Sep",
    10: "Okt",
    11: "Nov",
    12: "Des",
}

KPI_HEADER_WORDS = frozenset(
    {
        "target",
        "realisasi",
        "pencapaian",
        "actual",
        "nilai",
        "kpi",
        "indikator",
        "satuan",
        "-",
        "n/a",
        "na",
        "",
    }
)
KPI_SCALE_MAP = {
    "m": 1_000_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
    "k": 1_000,
    "rb": 1_000,
    "ribu": 1_000,
    "miliar": 1_000_000_000,
    "b": 1_000_000_000,
}

COLOR_THRESHOLD_PATTERN = re.compile(r"^\d+[–—\-]\d+%$|^[<≥≤>]=?\d+%$")
TRL_PATTERN = re.compile(r"(?i)trl\s*(\d+)")
TRL_EXACT_PATTERN = re.compile(r"(?i)^\s*trl\s*(\d+)\s*$")
KPI_OPERATOR_PATTERN = r"([≥≤><]|>=|<=)?"
KPI_NUMBER_PATTERN = r"(\d[\d.,]*)"
KPI_UNIT_PATTERN = r"\s*([a-zA-Z%/][^\s]*(?:\s+[a-zA-Z/][^\s]*)*)?"
KPI_EXPRESSION_PATTERN = re.compile(
    r"^\s*" + KPI_OPERATOR_PATTERN + r"\s*" + KPI_NUMBER_PATTERN + KPI_UNIT_PATTERN + r"\s*$",
    re.UNICODE,
)

DEFAULT_CHART_TYPE = "bar"
DEFAULT_SESSION_FOLDER = "unsessioned"
MAX_SIMPLE_CHART_ROWS = 12
MAX_PROGRESS_ROWS = 15
MAX_KPI_VALUE_PARSE_THRESHOLD = 0.4
NUMERIC_COLUMN_THRESHOLD = 0.9
COLOR_THRESHOLD_MATCH_RATIO = 0.8
LONG_TEXT_AVERAGE_LENGTH = 40
PROGRESS_GOOD_THRESHOLD = 100
PROGRESS_WARNING_THRESHOLD = 67

BLUE = "#2563EB"
GREEN = "#16A34A"
AMBER = "#D97706"
RED = "#DC2626"
SLATE = "#CBD5E1"
```

- [ ] **Step 2: Import constants in graphic service**

In `service/graphicService.py`, add:

```python
from service.graphicConstants import (
    AMBER,
    BLUE,
    CATEGORY_COLUMN_HINTS,
    COLOR_THRESHOLD_MATCH_RATIO,
    COLOR_THRESHOLD_PATTERN,
    DEFAULT_CHART_TYPE,
    DEFAULT_SESSION_FOLDER,
    GREEN,
    KPI_COLUMN_HINTS,
    KPI_EXPRESSION_PATTERN,
    KPI_HEADER_WORDS,
    KPI_SCALE_MAP,
    LONG_TEXT_AVERAGE_LENGTH,
    MAX_KPI_VALUE_PARSE_THRESHOLD,
    MAX_PROGRESS_ROWS,
    MAX_SIMPLE_CHART_ROWS,
    MONTH_COLUMN_HINTS,
    MONTH_LABELS,
    NOTES_HINTS,
    NUMERIC_COLUMN_THRESHOLD,
    PROGRESS_GOOD_THRESHOLD,
    PROGRESS_WARNING_THRESHOLD,
    RED,
    SLATE,
    SUPPORTED_CHART_TYPES,
    TARGET_COLUMN_HINTS,
    TRL_EXACT_PATTERN,
    TRL_PATTERN,
    VALUE_COLUMN_HINTS,
)
```

- [ ] **Step 3: Replace class and module constants**

Replace `KpiValueParser` class attributes:

```python
_HEADER_WORDS = KPI_HEADER_WORDS
_TRL_RE = TRL_EXACT_PATTERN
_EXPR_RE = KPI_EXPRESSION_PATTERN
_SCALE_MAP = KPI_SCALE_MAP
```

Replace module `_TRL_PATTERN` with `TRL_PATTERN` usage in `_parse_trl_value()`.

Replace `_COLOR_THRESHOLD_RE` usage with `COLOR_THRESHOLD_PATTERN`.

Replace `_NOTES_HINTS` usage with `NOTES_HINTS`.

Replace `GraphicSeervice.SUPPORTED_CHART_TYPES` with imported `SUPPORTED_CHART_TYPES`, or set:

```python
SUPPORTED_CHART_TYPES = SUPPORTED_CHART_TYPES
```

Use imported hints in `__init__()`:

```python
self.value_column_hints = VALUE_COLUMN_HINTS
self.target_column_hints = TARGET_COLUMN_HINTS
self.category_column_hints = CATEGORY_COLUMN_HINTS
self.month_column_hints = MONTH_COLUMN_HINTS
self.month_labels = MONTH_LABELS
```

- [ ] **Step 4: Replace magic numbers and strings**

Replace:

```python
"bar"
"unsessioned"
0.8
40
0.9
0.4
12
15
100
67
"#2563EB"
"#16A34A"
"#D97706"
"#DC2626"
"#CBD5E1"
```

With corresponding constants where they are behavior constants. Do not replace user-facing chart labels or error messages.

- [ ] **Step 5: Fix default mutable arguments**

Change signatures:

```python
def _pick_time_column(self, df: pd.DataFrame, exclude: list[str | None] | None = None) -> str | None:
    excl = [c for c in (exclude or []) if c]
```

```python
def _pick_kpi_column(self, df: pd.DataFrame, exclude: list[str | None] | None = None) -> str | None:
    excl = [c for c in (exclude or []) if c]
```

- [ ] **Step 6: Clean comments only**

Remove section banners and comments that describe direct code behavior. Keep comments explaining why one KPI render failure should not fail all graphics, or convert that to clear function name if practical.

- [ ] **Step 7: Run graphic tests**

Run:

```bash
pytest tests/graphicService_test.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add service/graphicConstants.py service/graphicService.py
git commit -m "refactor: extract graphic constants"
```

---

### Task 8: Final regression and cleanup

**Files:**
- Modify: only if tests reveal refactor regressions.
- Test: all focused and relevant existing tests.

- [ ] **Step 1: Run focused helper tests**

Run:

```bash
pytest tests/ambiguityParsing_test.py tests/clarificationHelpers_test.py tests/chatResponseBuilder_test.py -v
```

Expected: PASS.

- [ ] **Step 2: Run relevant regression tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py tests/chatPipeline_test.py tests/graphicService_test.py -v
```

Expected: PASS.

- [ ] **Step 3: Run import smoke check**

Run:

```bash
python - <<'PY'
from service.chatService import ChatService
from service.clarificationService import ClarificationService
from service.ambiguityDetectorService import AmbiguityDetectorService
from service.graphicService import GraphicSeervice
print("imports ok")
PY
```

Expected output:

```text
imports ok
```

- [ ] **Step 4: Check git diff for accidental behavior changes**

Run:

```bash
git diff -- service/chatService.py service/clarificationService.py service/ambiguityDetectorService.py service/graphicService.py
```

Expected: Diff shows helper extraction, constants, logging cleanup, and no endpoint/schema/repository contract changes.

- [ ] **Step 5: Commit final fixes if any**

If Step 1-4 required edits:

```bash
git add service tests
git commit -m "fix: stabilize service refactor"
```

If no edits required, skip commit.

---

## Self-Review

Spec coverage:

- Clean code and smaller helper units: covered by Tasks 1, 3, 5, 7.
- Chat orchestration cleanup: covered by Task 6.
- Clarification orchestration cleanup while preserving detector/generator separation: covered by Tasks 3 and 4.
- LLM-only ambiguity detector with parser extraction: covered by Tasks 1 and 2.
- Graphic constants and reduced magic strings: covered by Task 7.
- Focused tests: covered by Tasks 1, 3, 5.
- Relevant regression tests: covered by Tasks 2, 4, 6, 7, 8.

Placeholder scan: no placeholder tasks, no deferred implementation steps.

Type consistency: helper names used by service wiring tasks match helper definitions in earlier tasks.
