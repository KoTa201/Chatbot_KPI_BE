# Session Preference Tree and Iterative Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stateless in-memory session preference tree updates, NodeMerge conflict handling, QuestionRefine query rewriting, and evidence-augmented ambiguity re-check to the clarification flow.

**Architecture:** Keep `ClarificationService` as orchestrator while preserving logical separation between ambiguity detection, CQ formatting, preference update, and query refinement. Add a focused in-memory preference tree service that is rebuilt per clarification response and never persisted. Query refinement uses original question plus additional information, then ambiguity detection re-checks the rewritten question with serialized tree context and round number.

**Tech Stack:** Python 3.10+, FastAPI service layer, Pydantic schemas, SQLAlchemy async repository pattern, pytest + pytest-asyncio, OpenAI-compatible LLM wrapper.

---

## File Structure

- Create `service/preferenceTreeService.py`
  - Owns `TreeNode`, `PreferenceTree`, `QAPair`, NodeMerge prompt invocation, deterministic NodeMerge fallback, tree serialization, and additional-information formatting.
  - Has no database, cache, or file persistence.

- Modify `template/promptTemplate.py`
  - Replace query rewrite prompt behavior with QuestionRefine semantics.
  - Add `build_node_merge_prompt(old_list, new_pair)`.
  - Add optional `additional_information` support to `build_query_disambiguation_prompt()`.

- Modify `schema/clarificationSchema.py`
  - Add fields needed for iterative flow results: `needs_more_clarification`, `clarification_message`, `preference_tree`, `refinement_round`.
  - Add `AmbiSource` to `PRD_AMBIGUITY_TYPES` because the approved spec requires full 7-type tree coverage.

- Modify `service/ambiguityDetectorService.py`
  - Stop skipping `AmbiSource` once schema taxonomy includes it.
  - Preserve current detector/CQ separation.

- Modify `service/clarificationService.py`
  - Import `PreferenceTree` and use it inside `handle_clarification_response()`.
  - Build QA set from answer ids and clarification question records.
  - Build additional information from non-skipped answers plus raw additional constraints.
  - Use QuestionRefine prompt for rewrite.
  - Re-check ambiguity after rewrite with serialized tree + round number.
  - If ambiguity remains, return nested `ClarificationMessageResponse` in `QueryDisambiguationResult` instead of continuing directly.

- Modify `controller/chatController.py`
  - If `handle_clarification_response()` returns `needs_more_clarification=True`, stream the clarification response instead of passing the rewritten query to the RAG pipeline.

- Modify `tests/clarificationMechanism_test.py`
  - Add tests for preference tree, NodeMerge, prompt builders, Lewati handling, additional constraints, full taxonomy, and iterative re-check.
  - Update stale tests that import deleted `clarificationQuestionGeneratorService.py` or patch `service.question_generator`.

- Modify `tests/chatStreaming_test.py`
  - Add controller streaming test for additional clarification response.

---

### Task 1: Add Stateless Preference Tree Service

**Files:**
- Create: `service/preferenceTreeService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing tests for tree construction and Lewati formatting**

Append this test class to `tests/clarificationMechanism_test.py`:

```python
class TestPreferenceTreeService:
    @pytest.mark.asyncio
    async def test_preference_tree_builds_leaf_map_and_records_lewati(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        tree = PreferenceTree(llm=None)
        await tree.update_tree([
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="'Terbaik' merujuk ke metrik apa?",
                answer="Achievement %",
            ),
            QAPair(
                level1="AmbiRef",
                level2="tahun lalu",
                question="'Tahun lalu' merujuk ke periode mana?",
                answer="Lewati",
            ),
        ])

        schema_leaf = tree.leaf_map[("AmbiSchema", "terbaik")]
        ref_leaf = tree.leaf_map[("AmbiRef", "tahun lalu")]

        assert schema_leaf.qa_list == [
            {"question": "'Terbaik' merujuk ke metrik apa?", "answer": "Achievement %"}
        ]
        assert ref_leaf.qa_list == [
            {"question": "'Tahun lalu' merujuk ke periode mana?", "answer": "Lewati"}
        ]

        serialized = tree.serialize()
        assert serialized["children"]["AmbiSchema"]["children"]["terbaik"]["children"]["leaf"]["qa_list"][0]["answer"] == "Achievement %"
        assert serialized["children"]["AmbiRef"]["children"]["tahun lalu"]["children"]["leaf"]["qa_list"][0]["answer"] == "Lewati"

    def test_additional_information_excludes_lewati_and_appends_constraints(self):
        from service.preferenceTreeService import PreferenceTree, QAPair

        tree = PreferenceTree(llm=None)
        qa_set = [
            QAPair(
                level1="AmbiSchema",
                level2="terbaik",
                question="'Terbaik' merujuk ke metrik apa?",
                answer="Achievement %",
            ),
            QAPair(
                level1="AmbiRef",
                level2="tahun lalu",
                question="'Tahun lalu' merujuk ke periode mana?",
                answer="Lewati",
            ),
        ]

        additional_info = tree.build_additional_information(
            qa_set=qa_set,
            additional_constraints="hanya divisi aktif",
        )

        assert "Achievement %" in additional_info
        assert "hanya divisi aktif" in additional_info
        assert "Lewati" not in additional_info
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/clarificationMechanism_test.py::TestPreferenceTreeService -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'service.preferenceTreeService'`.

- [ ] **Step 3: Create preference tree service**

Create `service/preferenceTreeService.py`:

```python
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from template.promptTemplate import build_node_merge_prompt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QAPair:
    level1: str
    level2: str
    question: str
    answer: str


@dataclass
class TreeNode:
    level1: str | None = None
    level2: str | None = None
    node_type: str = "root"
    children: dict[str, "TreeNode"] = field(default_factory=dict)
    qa_list: list[dict[str, str]] = field(default_factory=list)

    def serialize(self) -> dict[str, Any]:
        return {
            "level1": self.level1,
            "level2": self.level2,
            "node_type": self.node_type,
            "children": {
                key: child.serialize() for key, child in self.children.items()
            },
            "qa_list": self.qa_list,
        }


class PreferenceTree:
    def __init__(self, llm=None):
        self.llm = llm
        self.root = TreeNode(node_type="root")
        self.leaf_map: dict[tuple[str, str], TreeNode] = {}

    async def update_tree(self, qa_set: list[QAPair]) -> None:
        for qa in qa_set:
            await self.add_qa(
                level1=qa.level1,
                level2=qa.level2,
                question=qa.question,
                answer=qa.answer,
            )

    async def add_qa(self, level1: str, level2: str, question: str, answer: str) -> None:
        level1_node = self.root.children.setdefault(
            level1,
            TreeNode(level1=level1, node_type="level1"),
        )
        level2_node = level1_node.children.setdefault(
            level2,
            TreeNode(level1=level1, level2=level2, node_type="level2"),
        )
        leaf = level2_node.children.setdefault(
            "leaf",
            TreeNode(level1=level1, level2=level2, node_type="leaf"),
        )
        self.leaf_map[(level1, level2)] = leaf
        leaf.qa_list = await self._node_merge(
            old_list=leaf.qa_list,
            new_pair={"question": question, "answer": answer},
        )

    async def _node_merge(
        self,
        old_list: list[dict[str, str]],
        new_pair: dict[str, str],
    ) -> list[dict[str, str]]:
        if self.llm is None or not old_list:
            return self._deterministic_merge(old_list, new_pair)

        try:
            prompt = build_node_merge_prompt(old_list=old_list, new_pair=new_pair)
            response = await self.llm._call_llm(
                prompt=prompt,
                temperature=0.0,
                max_output_tokens=500,
            )
            merged = json.loads(response.strip())
            if not isinstance(merged, list):
                raise ValueError("NodeMerge response must be a list")
            normalized = []
            for item in merged:
                if not isinstance(item, dict):
                    raise ValueError("NodeMerge item must be an object")
                question = str(item.get("question", "")).strip()
                answer = str(item.get("answer", "")).strip()
                if question and answer:
                    normalized.append({"question": question, "answer": answer})
            if not normalized:
                raise ValueError("NodeMerge response was empty after normalization")
            return normalized
        except Exception as exc:
            logger.warning("[PreferenceTree] NodeMerge failed, using deterministic merge: %s", exc)
            return self._deterministic_merge(old_list, new_pair)

    @staticmethod
    def _deterministic_merge(
        old_list: list[dict[str, str]],
        new_pair: dict[str, str],
    ) -> list[dict[str, str]]:
        new_question = new_pair["question"].strip().lower()
        filtered = [
            item for item in old_list
            if item.get("question", "").strip().lower() != new_question
        ]
        return [*filtered, new_pair]

    def serialize(self) -> dict[str, Any]:
        return self.root.serialize()

    def build_additional_information(
        self,
        qa_set: list[QAPair],
        additional_constraints: str | None = None,
    ) -> str:
        lines: list[str] = []
        for qa in qa_set:
            if qa.answer == "Lewati":
                continue
            lines.append(f"- {qa.question}: {qa.answer}")
        if additional_constraints:
            lines.append(f"- Constraint tambahan: {additional_constraints.strip()}")
        if not lines:
            return "Tidak ada informasi tambahan selain klarifikasi yang dilewati."
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/clarificationMechanism_test.py::TestPreferenceTreeService -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/preferenceTreeService.py tests/clarificationMechanism_test.py
git commit -m "feat: add stateless preference tree"
```

---

### Task 2: Add QuestionRefine and NodeMerge Prompts

**Files:**
- Modify: `template/promptTemplate.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing prompt tests**

Append these tests to `class TestKPIPrompts` in `tests/clarificationMechanism_test.py`:

```python
    def test_query_disambiguation_prompt_uses_question_refine_contract(self):
        prompt = build_query_disambiguation_prompt(
            original_query="List all novels published after 2000 that won a Booker Prize.",
            clarification_answers=[],
            additional_constraints="Only include novels published after 2010.",
        )

        assert "Absolute Preservation" in prompt
        assert "Full Integration" in prompt
        assert "Conflict Resolution" in prompt
        assert "Natural Language" in prompt
        assert "Original question:" in prompt
        assert "Additional information:" in prompt
        assert "Only include novels published after 2010." in prompt
        assert "Return **only** the text of the rewritten question." in prompt

    def test_node_merge_prompt_returns_json_array_contract(self):
        from template.promptTemplate import build_node_merge_prompt

        prompt = build_node_merge_prompt(
            old_list=[{"question": "Metrik terbaik mana?", "answer": "Realisasi"}],
            new_pair={"question": "'Terbaik' merujuk ke metrik apa?", "answer": "Achievement %"},
        )

        assert "Merge a new question-answer pair" in prompt
        assert "old_list" in prompt
        assert "new_pair" in prompt
        assert "same or highly similar meaning" in prompt
        assert "Return ONLY the merged list as a valid JSON array" in prompt
        assert "Achievement %" in prompt
```

- [ ] **Step 2: Run prompt tests to verify they fail**

Run: `pytest tests/clarificationMechanism_test.py::TestKPIPrompts::test_query_disambiguation_prompt_uses_question_refine_contract tests/clarificationMechanism_test.py::TestKPIPrompts::test_node_merge_prompt_returns_json_array_contract -v`

Expected: FAIL because `build_node_merge_prompt` is missing and the query prompt still uses the old disambiguator format.

- [ ] **Step 3: Update prompt template functions**

In `template/promptTemplate.py`, replace `build_query_disambiguation_prompt()` with:

```python
def build_query_disambiguation_prompt(
    original_query: str,
    clarification_answers: list,
    additional_constraints: str | None = None,
    additional_information: str | None = None,
) -> str:
    if additional_information is None:
        answer_lines = []
        for answer in clarification_answers:
            selected = getattr(answer, "selected_option", None) or answer.get("selected_option")
            free_text = getattr(answer, "free_text", None) if not isinstance(answer, dict) else answer.get("free_text")
            question_id = getattr(answer, "question_id", None) or answer.get("question_id")
            effective_answer = free_text if selected == "Lainnya" and free_text else selected
            if effective_answer == "Lewati":
                continue
            answer_lines.append(f"- {question_id}: {effective_answer}")
        if additional_constraints:
            answer_lines.append(f"- Constraint tambahan: {additional_constraints}")
        additional_information = "\n".join(answer_lines) if answer_lines else "Tidak ada informasi tambahan."

    return f'''## Task
To combine an `original_question` with `additional_information` into a single, coherent, and complete new question that is logically sound and easy to understand.

## Core Principles
1.  **Absolute Preservation**: You MUST preserve ALL constraints, details, and intents from the `original_question`. Nothing from the original should be omitted or altered unless it is directly and explicitly contradicted by the `additional_information`.
2.  **Full Integration**: You MUST seamlessly integrate ALL new requirements and constraints from the `additional_information` into the new question.
3.  **Conflict Resolution**: If a piece of `additional_information` directly conflicts with a part of the `original_question`, the `additional_information` takes precedence and should be used to update or replace the conflicting part. This is the **only** scenario where original information may be modified.
4.  **Natural Language**: The final output must be a single, natural-sounding question, not a list of criteria.

## Examples
Original question: List all novels published after 2000 that won a Booker Prize.
Additional information: Only include novels published after 2010 that were also adapted into movies and written by female authors.
Rewritten question: List all novels published after 2010 that won a Booker Prize, were adapted into movies, and were written by female authors.

Original question: Which Asian countries have a GDP per capita above $30,000 and a population under 10 million?
Additional information: Exclude countries that are island nations and with a population more than 10 million.
Rewritten question: Which Asian countries that are not island nations have a GDP per capita above $30,000 and a population more than 10 million?

Original question: Provide the list of Olympic gold medalists in swimming events for the last three Summer Olympics, including their ages at the time of winning.
Additional information: I am only interested in male athletes from North America, and only in individual events.
Rewritten question: Provide the list of male North American Olympic gold medalists in individual swimming events for the last three Summer Olympics, including their ages at the time of winning.

## Response Format
- Return **only** the text of the rewritten question.
- Do not include any preamble, labels (like "Rewritten question:"), or explanations.

---
**Input:**
Original question: {original_query}
Additional information: {additional_information}

The rewritten question is:
'''
```

Add this function after it:

```python
def build_node_merge_prompt(old_list: list[dict], new_pair: dict) -> str:
    import json

    return f'''## Task
Merge a new question-answer pair into an existing list of question-answer pairs.

## Input
- old_list: existing list of objects, each with a `question` and `answer` field.
- new_pair: object with a `question` and `answer` field.

old_list:
{json.dumps(old_list, ensure_ascii=False)}

new_pair:
{json.dumps(new_pair, ensure_ascii=False)}

## Merge Instructions
1. Compare the `question` field of `new_pair` with each item in `old_list`. If any question in `old_list` has the same or highly similar meaning as `new_pair` (same intent, possibly different wording), treat it as a conflict.
2. If there is a conflict, remove the conflicting item and replace it with `new_pair`.
3. If there is no conflict, append `new_pair` at the end.
4. Ensure the output list contains no duplicate questions by meaning.
5. Return ONLY the merged list as a valid JSON array: [{"question": "...", "answer": "..."}, ...]
6. Do NOT return any explanation or text outside the JSON array.
'''
```

- [ ] **Step 4: Run prompt tests to verify they pass**

Run: `pytest tests/clarificationMechanism_test.py::TestKPIPrompts::test_query_disambiguation_prompt_uses_question_refine_contract tests/clarificationMechanism_test.py::TestKPIPrompts::test_node_merge_prompt_returns_json_array_contract -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add template/promptTemplate.py tests/clarificationMechanism_test.py
git commit -m "feat: add refinement and node merge prompts"
```

---

### Task 3: Support Full PRD Taxonomy Including AmbiSource

**Files:**
- Modify: `schema/clarificationSchema.py`
- Modify: `service/ambiguityDetectorService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing full-taxonomy tests**

Replace `TestPRDSchemas.test_prd_ambiguity_types_use_ambiintent_not_ambisource` with:

```python
    def test_prd_ambiguity_types_cover_all_seven_types(self):
        assert PRD_AMBIGUITY_TYPES == {
            "AmbiSchema",
            "AmbiValue",
            "AmbiIntent",
            "AmbiSource",
            "AmbiContext",
            "AmbiFallacy",
            "AmbiRef",
            "none",
        }
```

Replace `test_detector_skips_ambisource_question_set_items` with:

```python
@pytest.mark.asyncio
async def test_detector_accepts_ambisource_question_set_items():
    detector = AmbiguityDetectorService()

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '''{
            "has_ambiguity": true,
            "question_set": [
                {
                    "question": "Sumber interpretasi bisnis mana yang Anda maksud?",
                    "level_1_label": "LLM-sourced ambiguity",
                    "level_2_label": "AmbiSource",
                    "description": {
                        "options": ["Definisi internal KPI", "Aturan konversi eksternal"]
                    }
                }
            ]
        }'''

        result = await detector._assess_ambiguity_with_llm(
            user_query="Tampilkan data KPI berdasarkan sumber konversi",
            user_role="Owner",
            kpi_context="KPI context"
        )

    assert result.is_ambiguous is True
    assert result.ambiguity_type == "AmbiSource"
    assert result.detected_ambiguities[0].metadata.get("is_ambiguity_level1_type_llm") is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/clarificationMechanism_test.py::TestPRDSchemas::test_prd_ambiguity_types_cover_all_seven_types tests/clarificationMechanism_test.py::test_detector_accepts_ambisource_question_set_items -v`

Expected: FAIL because `AmbiSource` is excluded.

- [ ] **Step 3: Add AmbiSource to schema taxonomy**

In `schema/clarificationSchema.py`, update `PRD_AMBIGUITY_TYPES` to:

```python
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
```

- [ ] **Step 4: Remove AmbiSource skip comment**

In `service/ambiguityDetectorService.py`, change this comment:

```python
# Skip unsupported types (AmbiSource, AmbiView, etc.)
```

to:

```python
# Skip unsupported types outside the PRD taxonomy.
```

Keep the existing condition:

```python
if level_2_label not in PRD_AMBIGUITY_TYPES or level_2_label == "none":
```

- [ ] **Step 5: Run taxonomy tests to verify they pass**

Run: `pytest tests/clarificationMechanism_test.py::TestPRDSchemas::test_prd_ambiguity_types_cover_all_seven_types tests/clarificationMechanism_test.py::test_detector_accepts_ambisource_question_set_items -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add schema/clarificationSchema.py service/ambiguityDetectorService.py tests/clarificationMechanism_test.py
git commit -m "feat: support full ambiguity taxonomy"
```

---

### Task 4: Integrate Preference Tree and QuestionRefine in ClarificationService

**Files:**
- Modify: `schema/clarificationSchema.py`
- Modify: `service/clarificationService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing service integration tests**

Append these tests under `class TestClarificationService`:

```python
    @pytest.mark.asyncio
    async def test_handle_clarification_response_uses_preference_tree_additional_information(self):
        service = ClarificationService(db=None)
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguous_phrase="terbaik",
                ambiguity_type="AmbiSchema",
                clarification_question="'Terbaik' merujuk ke metrik apa?",
            ),
            SimpleNamespace(
                clarification_question_id="q2",
                ambiguous_phrase="tahun lalu",
                ambiguity_type="AmbiRef",
                clarification_question="'Tahun lalu' merujuk ke periode mana?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=False,
            ambiguity_type="none",
            ambiguity_score=0.0,
            detected_ambiguities=[],
        ))

        captured_prompt = {}

        async def fake_call_llm(**kwargs):
            captured_prompt["prompt"] = kwargs["prompt"]
            return "Tampilkan sales dengan Achievement % tertinggi hanya divisi aktif"

        service.llm._call_llm = fake_call_llm

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Achievement %"),
                ClarificationAnswerItem(question_id="q2", selected_option="Lewati"),
            ],
            additional_constraints="hanya divisi aktif",
            original_query="Tampilkan sales terbaik tahun lalu",
        )

        assert result.disambiguated_query == "Tampilkan sales dengan Achievement % tertinggi hanya divisi aktif"
        assert result.needs_more_clarification is False
        assert "Achievement %" in captured_prompt["prompt"]
        assert "hanya divisi aktif" in captured_prompt["prompt"]
        assert "Lewati" not in captured_prompt["prompt"]
        assert result.preference_tree is not None
        assert result.preference_tree["children"]["AmbiRef"]["children"]["tahun lalu"]["children"]["leaf"]["qa_list"][0]["answer"] == "Lewati"

    @pytest.mark.asyncio
    async def test_handle_clarification_response_returns_next_questions_when_recheck_is_ambiguous(self):
        service = ClarificationService(db=None)
        service.repo.get_by_session = AsyncMock(return_value=[
            SimpleNamespace(
                clarification_question_id="q1",
                ambiguous_phrase="performa",
                ambiguity_type="AmbiIntent",
                clarification_question="Performa ingin dilihat sebagai ranking atau ringkasan?",
            ),
        ])
        service.repo.update_with_answer = AsyncMock()
        service.repo.create = AsyncMock(return_value=SimpleNamespace(clarification_question_id="q-next"))
        service.llm._call_llm = AsyncMock(return_value="Tampilkan ranking performa KPI berdasarkan achievement")
        service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
            is_ambiguous=True,
            ambiguity_type="AmbiSchema",
            ambiguity_score=0.91,
            detection_source="llm",
            detected_ambiguities=[
                DetectedAmbiguity(
                    ambiguous_phrase="achievement",
                    ambiguity_type="AmbiSchema",
                    ambiguity_score=0.91,
                    suggested_clarifying_question="Achievement yang dimaksud metrik apa?",
                    answer_options=["Achievement %", "Weighted score"],
                )
            ],
        ))

        result = await service.handle_clarification_response(
            session_id=SESSION_TEST_2,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Ranking tertinggi"),
            ],
            original_query="Tampilkan performa KPI",
        )

        assert result.needs_more_clarification is True
        assert result.clarification_message is not None
        assert result.clarification_message.questions[0].question == "Achievement yang dimaksud metrik apa?"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/clarificationMechanism_test.py::TestClarificationService::test_handle_clarification_response_uses_preference_tree_additional_information tests/clarificationMechanism_test.py::TestClarificationService::test_handle_clarification_response_returns_next_questions_when_recheck_is_ambiguous -v`

Expected: FAIL because `handle_clarification_response()` does not accept `original_query`, result schema lacks fields, and no re-check loop exists.

- [ ] **Step 3: Extend `QueryDisambiguationResult` schema**

In `schema/clarificationSchema.py`, update `QueryDisambiguationResult` to:

```python
class QueryDisambiguationResult(BaseModel):
    """Hasil disambiguasi query setelah mendapat jawaban klarifikasi."""
    original_query: str
    disambiguated_query: str
    clarification_answers: list[ClarificationAnswerItem] = Field(default_factory=list)
    additional_constraints: Optional[str] = None
    clarifying_question: Optional[str] = None
    clarification_answer: Optional[str] = None
    needs_more_clarification: bool = False
    clarification_message: Optional[ClarificationMessageResponse] = None
    preference_tree: Optional[dict[str, Any]] = None
    refinement_round: int = 1
```

- [ ] **Step 4: Import preference tree types**

In `service/clarificationService.py`, add:

```python
from service.preferenceTreeService import PreferenceTree, QAPair
```

- [ ] **Step 5: Update `handle_clarification_response()` signature and original query fallback**

Change the signature to:

```python
    async def handle_clarification_response(
        self,
        session_id: UUID,
        clarification_answers: list[ClarificationAnswerItem],
        additional_constraints: str | None = None,
        original_query: str | None = None,
        refinement_round: int = 1,
    ) -> QueryDisambiguationResult:
```

Replace:

```python
        original_query = logs[0].ambiguous_phrase or ""
```

with:

```python
        source_query = original_query or logs[-1].ambiguous_phrase or ""
```

Use `source_query` in the rest of the method.

- [ ] **Step 6: Add QA set builder helper**

Add this method to `ClarificationService` before `_disambiguate_query()`:

```python
    @staticmethod
    def _build_qa_set(
        clarification_answers: list[ClarificationAnswerItem],
        log_by_id: dict[str, object],
    ) -> list[QAPair]:
        qa_set: list[QAPair] = []
        for answer in clarification_answers:
            log = log_by_id[answer.question_id]
            effective_answer = answer.free_text if answer.selected_option == "Lainnya" and answer.free_text else answer.selected_option
            qa_set.append(
                QAPair(
                    level1=getattr(log, "ambiguity_type", None) or "unknown",
                    level2=getattr(log, "ambiguous_phrase", None) or getattr(log, "clarification_question", None) or answer.question_id,
                    question=getattr(log, "clarification_question", None) or answer.question_id,
                    answer=effective_answer,
                )
            )
        return qa_set
```

- [ ] **Step 7: Build tree and additional information before rewrite**

Inside `handle_clarification_response()`, after missing-id validation, add:

```python
        qa_set = self._build_qa_set(clarification_answers, log_by_id)
        preference_tree = PreferenceTree(llm=self.llm)
        await preference_tree.update_tree(qa_set)
        additional_information = preference_tree.build_additional_information(
            qa_set=qa_set,
            additional_constraints=additional_constraints,
        )
```

- [ ] **Step 8: Pass additional information into rewrite**

Change the `_disambiguate_query()` call to:

```python
        disambiguated_query = await self._disambiguate_query(
            original_query=source_query,
            clarification_answers=clarification_answers,
            additional_constraints=additional_constraints,
            additional_information=additional_information,
        )
```

Update `_disambiguate_query()` signature to include:

```python
        additional_information: str | None = None,
```

Update its prompt call to:

```python
            prompt = build_query_disambiguation_prompt(
                original_query=original_query,
                clarification_answers=clarification_answers,
                additional_constraints=additional_constraints,
                additional_information=additional_information,
            )
```

- [ ] **Step 9: Add evidence-augmented re-check helper**

Add this method to `ClarificationService` after `_disambiguate_query()`:

```python
    async def _recheck_ambiguity_after_refinement(
        self,
        rewritten_query: str,
        user_role: str,
        preference_tree: PreferenceTree,
        refinement_round: int,
    ):
        import json

        evidence_context = (
            f"Refinement round: {refinement_round}\n"
            f"Serialized preference tree: {json.dumps(preference_tree.serialize(), ensure_ascii=False)}"
        )
        try:
            return await self.ambiguity_detector.detect_ambiguity(
                rewritten_query,
                user_role,
                evidence_context,
            )
        except Exception as exc:
            logger.warning("[ClarificationService] Ambiguity re-check failed: %s", exc)
            return None
```

- [ ] **Step 10: Add helper to create next clarification response**

Add this method near `_generate_clarifying_question()`:

```python
    async def _build_clarification_response_from_detection(
        self,
        session_id: UUID,
        user_id: UUID | None,
        user_role: str,
        original_query: str,
        ambiguity_result,
    ) -> ClarificationMessageResponse | None:
        if not ambiguity_result or not ambiguity_result.is_ambiguous:
            return None

        detected = sorted(
            ambiguity_result.detected_ambiguities,
            key=lambda item: item.ambiguity_score,
            reverse=True,
        )[: self.MAX_QUESTIONS_PER_BATCH]
        if not detected:
            return None

        questions: list[ClarificationQuestionResponse] = []
        for ambiguity in detected:
            clarifying_q = await self._generate_clarifying_question(
                ambiguity_type=ambiguity.ambiguity_type,
                suggested_question=ambiguity.suggested_clarifying_question,
                suggested_options=ambiguity.answer_options,
                ambiguous_phrase=ambiguity.ambiguous_phrase,
                metadata=ambiguity.metadata,
            )
            log = await self.repo.create(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                original_query=ambiguity.ambiguous_phrase or original_query,
                ambiguity_score=ambiguity.ambiguity_score,
                ambiguity_type=ambiguity.ambiguity_type,
                decision="clarify",
                decision_source=ambiguity_result.detection_source,
                is_ambiguity_level1_type_llm=ambiguity.metadata.get("is_ambiguity_level1_type_llm"),
                clarifying_question=clarifying_q.clarifying_question,
                answer_options=clarifying_q.options,
            )
            questions.append(
                ClarificationQuestionResponse(
                    id=str(log.clarification_question_id),
                    ambiguous_phrase=getattr(clarifying_q, "ambiguous_phrase", None),
                    ambiguity_type=getattr(clarifying_q, "ambiguity_type", ambiguity.ambiguity_type),
                    question=clarifying_q.clarifying_question,
                    options=clarifying_q.options,
                    metadata=getattr(clarifying_q, "metadata", {}),
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

- [ ] **Step 11: Call re-check and return `QueryDisambiguationResult` fields**

After answer updates, add:

```python
        recheck_result = await self._recheck_ambiguity_after_refinement(
            rewritten_query=disambiguated_query,
            user_role="User",
            preference_tree=preference_tree,
            refinement_round=refinement_round,
        )
        next_clarification = None
        if recheck_result and recheck_result.is_ambiguous and refinement_round < 3:
            next_clarification = await self._build_clarification_response_from_detection(
                session_id=session_id,
                user_id=None,
                user_role="User",
                original_query=disambiguated_query,
                ambiguity_result=recheck_result,
            )
```

Return:

```python
        return QueryDisambiguationResult(
            original_query=source_query,
            clarification_answers=clarification_answers,
            disambiguated_query=disambiguated_query,
            additional_constraints=additional_constraints,
            needs_more_clarification=next_clarification is not None,
            clarification_message=next_clarification,
            preference_tree=preference_tree.serialize(),
            refinement_round=refinement_round,
        )
```

- [ ] **Step 12: Run service tests to verify they pass**

Run: `pytest tests/clarificationMechanism_test.py::TestClarificationService::test_handle_clarification_response_uses_preference_tree_additional_information tests/clarificationMechanism_test.py::TestClarificationService::test_handle_clarification_response_returns_next_questions_when_recheck_is_ambiguous -v`

Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add schema/clarificationSchema.py service/clarificationService.py tests/clarificationMechanism_test.py
git commit -m "feat: integrate preference tree refinement"
```

---

### Task 5: Return Additional Clarification From Controller

**Files:**
- Modify: `controller/chatController.py`
- Modify: `tests/chatStreaming_test.py`

- [ ] **Step 1: Write failing controller streaming test**

Append this test to `tests/chatStreaming_test.py`:

```python
@pytest.mark.asyncio
async def test_handle_clarification_streams_next_clarification_without_rag(monkeypatch):
    from schema.clarificationSchema import ClarificationMessageResponse, ClarificationQuestionResponse

    captured = {"rag_called": False}

    class FakeClarificationService:
        def __init__(self, db):
            self.db = db

        async def handle_clarification_response(self, **kwargs):
            return SimpleNamespace(
                disambiguated_query="Tampilkan ranking performa KPI",
                needs_more_clarification=True,
                clarification_message=ClarificationMessageResponse(
                    session_id=SESSION_STREAM_CLARIFICATION,
                    message_type="clarification",
                    clarifying_question="Achievement yang dimaksud metrik apa?",
                    options=["Achievement %", "Weighted score", "Lewati", "Lainnya"],
                    questions=[
                        ClarificationQuestionResponse(
                            id="q-next",
                            ambiguous_phrase="achievement",
                            ambiguity_type="AmbiSchema",
                            question="Achievement yang dimaksud metrik apa?",
                            options=["Achievement %", "Weighted score", "Lewati", "Lainnya"],
                        )
                    ],
                ),
            )

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured["rag_called"] = True
            raise AssertionError("RAG pipeline should not run when more clarification is needed")

    monkeypatch.setattr(chat_controller_module, "ClarificationService", FakeClarificationService)
    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)
    response = await controller.handle_clarification(
        request=ChatRequest(
            message="Lanjut",
            session_id=SESSION_STREAM_CLARIFICATION,
            clarification_answers=[
                ClarificationAnswerItem(question_id="q1", selected_option="Ranking tertinggi"),
            ],
        ),
        current_user=_fake_user(role="kepala_divisi"),
    )

    events = await _read_sse_events(response)
    assert captured["rag_called"] is False
    metadata = events[0][1]
    assert metadata["clarification_questions"][0]["question"] == "Achievement yang dimaksud metrik apa?"
    streamed_message = "".join(
        payload["chunk"] for event_name, payload in events if event_name == "message"
    )
    assert streamed_message == "Achievement yang dimaksud metrik apa?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/chatStreaming_test.py::test_handle_clarification_streams_next_clarification_without_rag -v`

Expected: FAIL because controller always continues to `ChatService.process_query()`.

- [ ] **Step 3: Pass original query into clarification service**

In `controller/chatController.py`, change the call to `handle_clarification_response()` to include:

```python
                original_query=request.message,
```

- [ ] **Step 4: Return clarification stream when more clarification is needed**

After `disambiguation_result = await clarification_service.handle_clarification_response(...)`, add:

```python
        if getattr(disambiguation_result, "needs_more_clarification", False):
            clarification_message = disambiguation_result.clarification_message
            response = ChatResponse(
                session_id=request.session_id,
                message=clarification_message.clarifying_question or "Klarifikasi diperlukan sebelum query KPI dijalankan.",
                clarification_message_answer_options=clarification_message.options,
                clarification_questions=clarification_message.questions,
            )
            return self._build_streaming_response(response)
```

- [ ] **Step 5: Run controller test to verify it passes**

Run: `pytest tests/chatStreaming_test.py::test_handle_clarification_streams_next_clarification_without_rag -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add controller/chatController.py tests/chatStreaming_test.py
git commit -m "feat: stream iterative clarification responses"
```

---

### Task 6: Clean Up Stale Clarification Tests and Run Targeted Suite

**Files:**
- Modify: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Remove deleted service import**

In `tests/clarificationMechanism_test.py`, remove:

```python
from service.clarificationQuestionGeneratorService import (
    ClarificationQuestionGeneratorService,
)
```

- [ ] **Step 2: Remove stale generator-specific tests**

Delete these test blocks because the approved design says not to revive the standalone CQ generator service:

```python
class TestClarificationQuestionGenerator:
    ...
```

Delete standalone functions:

```python
@pytest.mark.asyncio
async def test_question_generator_appends_skip_and_other_to_suggested_options():
    ...

@pytest.mark.asyncio
async def test_question_generator_limits_options_before_defaults():
    ...
```

- [ ] **Step 3: Replace stale `service.question_generator` patch test**

In `TestClarificationService.test_process_clarification_needed`, replace the inner `with patch.object(service.question_generator, ...)` block with direct assertions:

```python
            result = await service.process_user_query(
                user_query="Siapa yang terbaik?",
                user_id=uuid4(),
                user_role="Owner",
                session_id=SESSION_TEST_2,
                clarification_count=0,
            )

            assert result is not None
            assert result.message_type == "clarification"
            assert result.clarifying_question == "Scope mana yang Anda maksud?"
            assert result.options == ["Per individu", "Per divisi"]
```

- [ ] **Step 4: Run targeted clarification suite**

Run: `pytest tests/clarificationMechanism_test.py -v`

Expected: PASS or only failures unrelated to removed standalone generator assumptions.

- [ ] **Step 5: Fix any import/order failures exactly**

If the run fails due to missing imports, update imports so this set is present:

```python
import pytest
from uuid import UUID, uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
```

Keep existing schema/service imports that are still used.

- [ ] **Step 6: Run targeted clarification suite again**

Run: `pytest tests/clarificationMechanism_test.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/clarificationMechanism_test.py
git commit -m "test: align clarification tests with integrated cq flow"
```

---

### Task 7: Final Verification

**Files:**
- No code changes expected unless verification finds a defect.

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/clarificationMechanism_test.py tests/chatStreaming_test.py -v`

Expected: PASS.

- [ ] **Step 2: Run chat-related tests**

Run: `pytest tests/chatPipeline_test.py tests/chatStreaming_test.py tests/clarificationMechanism_test.py -v`

Expected: PASS.

- [ ] **Step 3: Inspect git diff**

Run: `git diff --stat`

Expected: Changes are limited to service/schema/controller/template/tests and the plan/spec docs.

- [ ] **Step 4: Inspect no migration files were added for this feature**

Run: `git status --short alembic/versions`

Expected: No new migration caused by this feature. Existing unrelated migration files may still appear from earlier work.

- [ ] **Step 5: Commit verification fixes if needed**

Only if Step 1 or Step 2 required fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize iterative clarification flow"
```

---

## Self-Review

- Spec coverage: Tasks cover module separation, stateless tree, NodeMerge prompt, QuestionRefine prompt, additional constraints path, Lewati behavior, ambiguity dependency handling through iterative re-check, full 7-type taxonomy, and evidence-augmented re-check.
- Placeholder scan: No task contains TBD/TODO/fill-in placeholders. Each code-changing step includes concrete code or exact replacement instructions.
- Type consistency: `QAPair`, `TreeNode`, `PreferenceTree`, `build_node_merge_prompt`, `additional_information`, `needs_more_clarification`, `clarification_message`, `preference_tree`, and `refinement_round` are introduced before use in later tasks.
