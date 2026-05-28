# Chatbot Authority Addon Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/chat/prompt` auto-select the active chatbot for the authenticated user's authority and apply `chatbot.addon_prompt` as a permanent LLM constraint.

**Architecture:** `ChatService` resolves the active chatbot from `ChatbotRepository` before any pipeline stage runs. Prompt builders accept an optional `addon_prompt` and append it as an additive instruction block without replacing existing safety/schema rules. `ClarificationService` and `AmbiguityDetectorService` thread the prompt into ambiguity assessment.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, pytest, pytest-asyncio.

---

## File Structure

- Modify `repository/chatbotRepository.py`: add active-chatbot lookup by authority.
- Modify `service/chatService.py`: resolve active chatbot before session/pipeline work; pass addon prompt into clarification, NL-to-SQL, and analysis prompts.
- Modify `service/clarificationService.py`: accept `addon_prompt` in `process_user_query` and pass to ambiguity detector.
- Modify `service/ambiguityDetectorService.py`: accept `addon_prompt` and pass to ambiguity prompt builder.
- Modify `template/promptTemplate.py`: add helper and optional `addon_prompt` parameters to relevant prompt builders.
- Modify `tests/chatStreaming_test.py`: assert controller passes normalized role unchanged to service.
- Modify `tests/clarificationMechanism_test.py`: add prompt builder assertions for addon prompt blocks.
- Create or modify `tests/chatbotAuthorityAddonPrompt_test.py`: service-level tests for chatbot resolution and pipeline prompt propagation.

---

### Task 1: Add Repository Lookup

**Files:**
- Modify: `repository/chatbotRepository.py`
- Test: `tests/chatbotAuthorityAddonPrompt_test.py`

- [ ] **Step 1: Write failing repository tests**

Create `tests/chatbotAuthorityAddonPrompt_test.py` with:

```python
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from model.Chatbot import AuthorityEnum, Chatbot
from repository.chatbotRepository import ChatbotRepository

pytestmark = pytest.mark.asyncio

CHATBOT_ID = UUID("00000000-0000-0000-0000-000000000301")


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return FakeScalarResult(self.value)


class FakeDb:
    def __init__(self, value):
        self.value = value
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.value)


async def test_get_active_by_authority_returns_matching_active_chatbot():
    chatbot = SimpleNamespace(
        id=CHATBOT_ID,
        authority=AuthorityEnum.KARYAWAN,
        is_active=True,
        addon_prompt="Gunakan bahasa singkat.",
    )
    db = FakeDb(chatbot)
    repo = ChatbotRepository(db)  # type: ignore[arg-type]

    result = await repo.get_active_by_authority(AuthorityEnum.KARYAWAN)

    assert result is chatbot
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "chatbots.authority = 'karyawan'" in compiled
    assert "chatbots.is_active = true" in compiled.lower()


async def test_get_active_by_authority_accepts_role_string():
    chatbot = SimpleNamespace(authority=AuthorityEnum.KEPALA_DIVISI, is_active=True)
    db = FakeDb(chatbot)
    repo = ChatbotRepository(db)  # type: ignore[arg-type]

    result = await repo.get_active_by_authority("kepala_divisi")

    assert result is chatbot
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "chatbots.authority = 'kepala_divisi'" in compiled
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_get_active_by_authority_returns_matching_active_chatbot tests/chatbotAuthorityAddonPrompt_test.py::test_get_active_by_authority_accepts_role_string -v
```

Expected: FAIL with `AttributeError: 'ChatbotRepository' object has no attribute 'get_active_by_authority'`.

- [ ] **Step 3: Add repository method**

In `repository/chatbotRepository.py`, add method after `get_by_chatbot_name`:

```python
    async def get_active_by_authority(self, authority: AuthorityEnum | str) -> Optional[Chatbot]:
        authority_value = authority.value if isinstance(authority, AuthorityEnum) else authority
        result = await self.db.execute(
            select(Chatbot).where(
                (Chatbot.authority == authority_value) &
                (Chatbot.is_active == True)
            )
        )
        return result.scalars().first()
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_get_active_by_authority_returns_matching_active_chatbot tests/chatbotAuthorityAddonPrompt_test.py::test_get_active_by_authority_accepts_role_string -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add repository/chatbotRepository.py tests/chatbotAuthorityAddonPrompt_test.py
git commit -m "feat: add active chatbot authority lookup"
```

---

### Task 2: Add Addon Prompt Blocks to Prompt Builders

**Files:**
- Modify: `template/promptTemplate.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing prompt tests**

Append to `tests/clarificationMechanism_test.py`:

```python
def test_nl_to_sql_prompt_includes_addon_prompt_constraint():
    from template.promptTemplate import build_nl_to_sql_prompt

    prompt = build_nl_to_sql_prompt(
        user_query="Tampilkan KPI saya",
        user_id=uuid4(),
        user_role="Karyawan",
        divisi=None,
        addon_prompt="Jawab hanya untuk KPI aktif.",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" in prompt
    assert "Jawab hanya untuk KPI aktif." in prompt


def test_analysis_prompt_includes_addon_prompt_constraint():
    from template.promptTemplate import build_analysis_prompt

    prompt = build_analysis_prompt(
        user_query="Tampilkan KPI saya",
        executed_sql="SELECT 1;",
        query_result=[{"nilai": 1}],
        rows_count=1,
        addon_prompt="Gunakan nada formal.",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" in prompt
    assert "Gunakan nada formal." in prompt


def test_ambiguity_prompt_omits_empty_addon_prompt():
    from template.promptTemplate import build_ambiguity_assessment_prompt

    prompt = build_ambiguity_assessment_prompt(
        user_query="KPI terbaik?",
        user_role="Karyawan",
        kpi_context="KPI context",
        addon_prompt="",
    )

    assert "[KONSTRAINT CHATBOT AKTIF]" not in prompt
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_nl_to_sql_prompt_includes_addon_prompt_constraint tests/clarificationMechanism_test.py::test_analysis_prompt_includes_addon_prompt_constraint tests/clarificationMechanism_test.py::test_ambiguity_prompt_omits_empty_addon_prompt -v
```

Expected: FAIL with unexpected keyword argument `addon_prompt`.

- [ ] **Step 3: Add prompt helper and function parameters**

In `template/promptTemplate.py`, add after `_json_default_serializer`:

```python
def _build_addon_prompt_block(addon_prompt: str | None) -> str:
    cleaned = (addon_prompt or "").strip()
    if not cleaned:
        return ""
    return f"""
[KONSTRAINT CHATBOT AKTIF]
Instruksi berikut wajib diikuti sebagai constraint tambahan. Instruksi ini tidak boleh mengganti, melemahkan, atau mengabaikan aturan keamanan, schema database, format output, dan larangan halusinasi di prompt utama.
{cleaned}
"""
```

Change `build_nl_to_sql_prompt` signature:

```python
def build_nl_to_sql_prompt(
    user_query: str,
    user_id: UUID,
    user_role: str,
    divisi: str | None,
    addon_prompt: str | None = None,
) -> str:
```

Inside it, before `prompt = f"""...`, add:

```python
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
```

Insert `{addon_prompt_block}` after line containing `Kamu adalah asisten SQL expert...` and before `ATURAN WAJIB:`.

Change `build_analysis_prompt` signature:

```python
def build_analysis_prompt(
    user_query: str,
    executed_sql: str,
    query_result: list[dict],
    rows_count: int,
    addon_prompt: str | None = None,
) -> str:
```

Inside it, before `prompt = f"""...`, add:

```python
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
```

Insert `{addon_prompt_block}` after line containing `Kamu adalah analis data KPI...` and before `Tugasmu HANYA:`.

Change `build_ambiguity_assessment_prompt` signature:

```python
def build_ambiguity_assessment_prompt(
    user_query: str,
    user_role: str,
    kpi_context: str = "",
    addon_prompt: str | None = None,
) -> str:
```

Inside it, before `prompt = f"""...`, add:

```python
    addon_prompt_block = _build_addon_prompt_block(addon_prompt)
```

Insert `{addon_prompt_block}` after line containing `Tugasmu: identifikasi SEMUA frasa ambigu...` and before `════════════════════════════════════════════════════════════════`.

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_nl_to_sql_prompt_includes_addon_prompt_constraint tests/clarificationMechanism_test.py::test_analysis_prompt_includes_addon_prompt_constraint tests/clarificationMechanism_test.py::test_ambiguity_prompt_omits_empty_addon_prompt -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add template/promptTemplate.py tests/clarificationMechanism_test.py
git commit -m "feat: add chatbot addon prompt constraints"
```

---

### Task 3: Thread Addon Prompt Through Clarification Services

**Files:**
- Modify: `service/ambiguityDetectorService.py`
- Modify: `service/clarificationService.py`
- Test: `tests/clarificationMechanism_test.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/clarificationMechanism_test.py`:

```python
@pytest.mark.asyncio
async def test_ambiguity_detector_passes_addon_prompt_to_prompt_builder(monkeypatch):
    detector = AmbiguityDetectorService()
    captured = {}

    def fake_builder(user_query, user_role, kpi_context="", addon_prompt=None):
        captured["addon_prompt"] = addon_prompt
        return "prompt"

    monkeypatch.setattr("service.ambiguityDetectorService.build_ambiguity_assessment_prompt", fake_builder)

    with patch.object(detector.llm, 'call_model', new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '{"has_ambiguity": false, "question_set": []}'
        await detector.detect_ambiguity(
            "KPI terbaik?",
            "Karyawan",
            "KPI context",
            addon_prompt="Gunakan constraint bot.",
        )

    assert captured["addon_prompt"] == "Gunakan constraint bot."


@pytest.mark.asyncio
async def test_clarification_service_passes_addon_prompt_to_detector():
    service = ClarificationService(db=None)
    service.repo.create = AsyncMock()
    service.context_service.build_context = lambda: "KPI context"
    service.ambiguity_detector.detect_ambiguity = AsyncMock(return_value=AmbiguityAssessmentResult(
        is_ambiguous=False,
        ambiguity_type="none",
        ambiguity_score=0.0,
        detection_source="llm",
        detected_ambiguities=[],
    ))

    result = await service.process_user_query(
        user_query="Tampilkan KPI saya",
        user_role="Karyawan",
        session_id=SESSION_TEST_1,
        clarification_count=0,
        addon_prompt="Gunakan constraint bot.",
    )

    assert result is None
    service.ambiguity_detector.detect_ambiguity.assert_awaited_once_with(
        "Tampilkan KPI saya",
        "Karyawan",
        "KPI context",
        addon_prompt="Gunakan constraint bot.",
    )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_ambiguity_detector_passes_addon_prompt_to_prompt_builder tests/clarificationMechanism_test.py::test_clarification_service_passes_addon_prompt_to_detector -v
```

Expected: FAIL with unexpected keyword argument `addon_prompt`.

- [ ] **Step 3: Update ambiguity detector**

In `service/ambiguityDetectorService.py`, change `detect_ambiguity` signature:

```python
    async def detect_ambiguity(
        self,
        user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
    ) -> AmbiguityAssessmentResult:
```

Change call inside it:

```python
            result = await self._assess_ambiguity_with_llm(user_query, user_role, kpi_context, addon_prompt)
```

Change `_assess_ambiguity_with_llm` signature:

```python
    async def _assess_ambiguity_with_llm(
        self,
        user_query: str,
        user_role: str,
        kpi_context: str = "",
        addon_prompt: str | None = None,
    ) -> AmbiguityAssessmentResult:
```

Change prompt builder call:

```python
            prompt = build_ambiguity_assessment_prompt(
                user_query,
                user_role,
                kpi_context,
                addon_prompt=addon_prompt,
            )
```

- [ ] **Step 4: Update clarification service**

In `service/clarificationService.py`, change `process_user_query` signature:

```python
    async def process_user_query(
        self,
        user_query: str,
        user_role: str,
        session_id: UUID,
        clarification_count: int = 0,
        addon_prompt: str | None = None,
    ) -> ClarificationMessageResponse | None:
```

Change detector call:

```python
        ambiguity_result = await self.ambiguity_detector.detect_ambiguity(
            user_query,
            user_role,
            kpi_context,
            addon_prompt=addon_prompt,
        )
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_ambiguity_detector_passes_addon_prompt_to_prompt_builder tests/clarificationMechanism_test.py::test_clarification_service_passes_addon_prompt_to_detector -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add service/ambiguityDetectorService.py service/clarificationService.py tests/clarificationMechanism_test.py
git commit -m "feat: thread addon prompt into clarification"
```

---

### Task 4: Resolve Active Chatbot Before Pipeline

**Files:**
- Modify: `service/chatService.py`
- Test: `tests/chatbotAuthorityAddonPrompt_test.py`

- [ ] **Step 1: Write failing ChatService tests**

Append to `tests/chatbotAuthorityAddonPrompt_test.py`:

```python
from fastapi import HTTPException

import service.chatService as chat_service_module
from service.chatService import ChatService
from schema.chatSchema import ChatResponse


async def test_process_query_fails_when_no_active_chatbot(monkeypatch):
    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            return None

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)

    service = ChatService(db=None)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc:
        await service.process_query(
            user_message="Tampilkan KPI saya",
            user_id=UUID("00000000-0000-0000-0000-000000000401"),
            user_role="karyawan",
            user_divisi=None,
            session_id=None,
        )

    assert exc.value.status_code == 404
    assert "Tidak ada chatbot aktif" in exc.value.detail


async def test_process_query_resolves_chatbot_before_session_creation(monkeypatch):
    events = []

    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            events.append(("chatbot_lookup", authority))
            return SimpleNamespace(addon_prompt="Gunakan constraint bot.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
            events.append(("session_create", kwargs["session_id"]))

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", AsyncMock(return_value=("SELECT 1;", SimpleNamespace(is_visualize=False, chart_type=None))))
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=False, sanitized_sql=None, reason="blocked"))

    service = ChatService(db=None)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000402"),
        user_role="karyawan",
        user_divisi=None,
        session_id=None,
    )

    assert isinstance(response, ChatResponse)
    assert events[0][0] == "chatbot_lookup"
    assert events[1][0] == "session_create"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_fails_when_no_active_chatbot tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_resolves_chatbot_before_session_creation -v
```

Expected: FAIL with import/attribute issue for `ChatbotRepository` patch target or no 404 behavior.

- [ ] **Step 3: Import repository and initialize**

In `service/chatService.py`, add import near repository imports:

```python
from repository.chatbotRepository import ChatbotRepository
```

In `ChatService.__init__`, add:

```python
        self.chatbot_repo = ChatbotRepository(db)
```

- [ ] **Step 4: Add resolver method**

In `service/chatService.py`, add before `_build_pipeline_context`:

```python
    async def _get_active_chatbot_for_role(self, user_role: str):
        chatbot = await self.chatbot_repo.get_active_by_authority(user_role)
        if chatbot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tidak ada chatbot aktif yang dikonfigurasi untuk authority user ini.",
            )
        return chatbot
```

- [ ] **Step 5: Call resolver before session creation**

In `process_query`, after imports and before `session_id = session_id or uuid.uuid4()`, add:

```python
        active_chatbot = await self._get_active_chatbot_for_role(user_role)
        addon_prompt = getattr(active_chatbot, "addon_prompt", None)
```

- [ ] **Step 6: Run tests to verify pass**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_fails_when_no_active_chatbot tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_resolves_chatbot_before_session_creation -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service/chatService.py tests/chatbotAuthorityAddonPrompt_test.py
git commit -m "feat: require active chatbot for chat pipeline"
```

---

### Task 5: Pass Addon Prompt Through Chat Pipeline

**Files:**
- Modify: `service/chatService.py`
- Test: `tests/chatbotAuthorityAddonPrompt_test.py`

- [ ] **Step 1: Write failing pipeline prompt propagation test**

Append to `tests/chatbotAuthorityAddonPrompt_test.py`:

```python
async def test_process_query_passes_addon_prompt_to_pipeline_stages(monkeypatch):
    captured = {}

    class FakeChatbotRepo:
        def __init__(self, db):
            pass

        async def get_active_by_authority(self, authority):
            return SimpleNamespace(addon_prompt="Gunakan bahasa formal.")

    class FakeSessionService:
        def __init__(self, db):
            pass

        async def create_session_if_missing(self, **kwargs):
            return None

    class FakeClarificationService:
        def __init__(self, db):
            pass

        async def get_clarification_count_in_session(self, session_id):
            return 0

        async def process_user_query(self, **kwargs):
            captured["clarification_addon_prompt"] = kwargs["addon_prompt"]
            return None

    async def fake_nl_to_sql(self, **kwargs):
        captured["nl_addon_prompt"] = kwargs["addon_prompt"]
        return "SELECT 1;", SimpleNamespace(is_visualize=False, chart_type=None)

    async def fake_analysis(self, **kwargs):
        captured["analysis_addon_prompt"] = kwargs["addon_prompt"]
        return "Narasi hasil."

    monkeypatch.setattr(chat_service_module, "ChatbotRepository", FakeChatbotRepo)
    monkeypatch.setattr(chat_service_module, "ChatSessionService", FakeSessionService)
    monkeypatch.setattr("service.clarificationService.ClarificationService", FakeClarificationService)
    monkeypatch.setattr(ChatService, "_run_nl_to_sql_stage", fake_nl_to_sql)
    monkeypatch.setattr(ChatService, "_run_sql_validation_stage", lambda self, **kwargs: SimpleNamespace(is_valid=True, sanitized_sql="SELECT 1;", reason=None))
    monkeypatch.setattr(ChatService, "_run_sql_execution_stage", AsyncMock(return_value=([{"value": 1}], 1)))
    monkeypatch.setattr(ChatService, "_run_result_analysis_stage", fake_analysis)

    service = ChatService(db=None)  # type: ignore[arg-type]
    response = await service.process_query(
        user_message="Tampilkan KPI saya",
        user_id=UUID("00000000-0000-0000-0000-000000000403"),
        user_role="karyawan",
        user_divisi=None,
        session_id=UUID("00000000-0000-0000-0000-000000000404"),
    )

    assert response.message == "Narasi hasil."
    assert captured == {
        "clarification_addon_prompt": "Gunakan bahasa formal.",
        "nl_addon_prompt": "Gunakan bahasa formal.",
        "analysis_addon_prompt": "Gunakan bahasa formal.",
    }
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_passes_addon_prompt_to_pipeline_stages -v
```

Expected: FAIL with missing `addon_prompt` key.

- [ ] **Step 3: Pass addon prompt to clarification service**

In `service/chatService.py`, update clarification call:

```python
                clarification_response = await clarification_service.process_user_query(
                    user_query=user_message,
                    user_role=user_role,
                    session_id=session_id,
                    clarification_count=clarification_count,
                    addon_prompt=addon_prompt,
                )
```

- [ ] **Step 4: Pass addon prompt to stage methods**

In `process_query`, update `_run_nl_to_sql_stage` call:

```python
                    addon_prompt=addon_prompt,
```

Update `_run_result_analysis_stage` call:

```python
                addon_prompt=addon_prompt,
```

- [ ] **Step 5: Update stage method signatures and prompt builder calls**

Change `_run_nl_to_sql_stage` signature:

```python
    async def _run_nl_to_sql_stage(
        self,
        stages: list[PipelineStageInfo],
        user_message: str,
        user_id: UUID,
        user_role: str,
        user_divisi: str | None,
        pipeline: dict[str, Any],
        addon_prompt: str | None = None,
    ) -> tuple[str, VisualizationDecision]:
```

Update `build_nl_to_sql_prompt` call:

```python
            nl_prompt = build_nl_to_sql_prompt(
                user_query=user_message,
                user_id=user_id,
                user_role=user_role,
                divisi=user_divisi,
                addon_prompt=addon_prompt,
            )
```

Change `_run_result_analysis_stage` signature:

```python
    async def _run_result_analysis_stage(
        self,
        stages: list[PipelineStageInfo],
        user_query: str,
        executed_sql: str,
        query_result: list[dict],
        rows_count: int,
        addon_prompt: str | None = None,
    ) -> str:
```

Update `build_analysis_prompt` call:

```python
        analysis_prompt = build_analysis_prompt(
            user_query=user_query,
            executed_sql=executed_sql,
            query_result=query_result,
            rows_count=rows_count,
            addon_prompt=addon_prompt,
        )
```

- [ ] **Step 6: Run test to verify pass**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py::test_process_query_passes_addon_prompt_to_pipeline_stages -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add service/chatService.py tests/chatbotAuthorityAddonPrompt_test.py
git commit -m "feat: apply chatbot addon prompt in pipeline"
```

---

### Task 6: Verify Controller Role Flow and Regression Tests

**Files:**
- Modify: `tests/chatStreaming_test.py`

- [ ] **Step 1: Add controller role assertion test**

Append to `tests/chatStreaming_test.py`:

```python
@pytest.mark.asyncio
async def test_handle_chat_passes_authority_role_to_service(monkeypatch):
    captured = {}
    expected = ChatResponse(
        session_id=SESSION_STREAM_CHAT,
        message="OK",
    )

    class FakeChatService:
        def __init__(self, db):
            self.db = db

        async def process_query(self, **kwargs):
            captured.update(kwargs)
            return expected

    monkeypatch.setattr(chat_controller_module, "ChatService", FakeChatService)

    controller = ChatController(db=None)  # type: ignore[arg-type]
    await controller.handle_chat(
        request=ChatRequest(message="Tampilkan KPI saya"),
        current_user=_fake_user(role="karyawan"),  # type: ignore[arg-type]
    )

    assert captured["user_role"] == "karyawan"
```

- [ ] **Step 2: Run test to verify current behavior**

Run:

```bash
pytest tests/chatStreaming_test.py::test_handle_chat_passes_authority_role_to_service -v
```

Expected: FAIL if controller maps `karyawan` to `Karyawan`, because chatbot authority enum uses lowercase `karyawan`.

- [ ] **Step 3: Update controller role mapping**

In `controller/chatController.py`, replace `_to_chat_role` body with:

```python
    @staticmethod
    def _to_chat_role(role_value: str) -> str:
        return role_value.strip().lower()
```

- [ ] **Step 4: Run targeted tests**

Run:

```bash
pytest tests/chatStreaming_test.py::test_handle_chat_passes_authority_role_to_service tests/chatStreaming_test.py::test_handle_clarification_streams_message_and_keeps_metadata_non_stream -v
```

Expected: PASS. Existing clarification test should still pass with lowercase role.

- [ ] **Step 5: Run feature test set**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py tests/chatStreaming_test.py tests/clarificationMechanism_test.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add controller/chatController.py tests/chatStreaming_test.py
git commit -m "fix: use authority role for chat pipeline"
```

---

### Task 7: Full Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run full tests**

Run:

```bash
pytest -v
```

Expected: PASS. If unrelated existing failures appear, capture exact failure list and rerun only feature tests to prove this change works.

- [ ] **Step 2: Run focused feature tests**

Run:

```bash
pytest tests/chatbotAuthorityAddonPrompt_test.py tests/chatStreaming_test.py tests/clarificationMechanism_test.py -v
```

Expected: PASS.

- [ ] **Step 3: Check working tree**

Run:

```bash
git status --short
```

Expected: only intended modified files remain, or clean if commits were made.

---

## Self-Review

Spec coverage:
- Active chatbot by authenticated authority: Task 1, Task 4, Task 6.
- Fail when none exists: Task 4.
- Inactive matching chatbot counts as missing: repository query in Task 1 and service failure in Task 4.
- Other authority ignored: repository filter in Task 1.
- Addon prompt permanent constraint: Task 2, Task 3, Task 5.
- Null or empty addon prompt no-op: Task 2.

Placeholder scan: no TBD/TODO/fill-later steps remain.

Type consistency:
- `addon_prompt: str | None` used consistently across prompt builders, services, and tests.
- Role/authority stays lowercase (`karyawan`, `kepala_divisi`) before repository lookup.
