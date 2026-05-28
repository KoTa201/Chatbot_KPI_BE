# Chat Session Clarification Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove unused clarification `user_answer`, persist session chatbot ownership, and keep `chat_sessions.end_at` equal to latest message timestamp.

**Architecture:** Keep changes in existing chat and clarification boundaries. `ChatService` already resolves active chatbot; session creation should persist that chatbot ID. `ChatSessionRepository.create_message()` owns message persistence, so it should also update session last-activity timestamp from the created message.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, pytest, pytest-asyncio.

---

## File Structure

- Modify: `model/ClarificationQuestion.py` — remove `user_answer` ORM column and property fallback.
- Modify: `repository/clarificationRepository.py` — stop writing/parsing `user_answer`.
- Create: `alembic/versions/f6a7b8c9d0e1_drop_user_answer_from_clarification_questions.py` — drop column with downgrade restore.
- Modify: `service/chatSessionService.py` — accept `chatbot_id` when creating missing session.
- Modify: `service/chatService.py` — pass active chatbot ID into session creation.
- Modify: `repository/chatSessionRepository.py` — update session `end_at` from each created message timestamp.
- Modify: `tests/clarificationMechanism_test.py` — assert `user_answer` column removed.
- Modify: `tests/chatPipeline_test.py` — assert active chatbot ID is passed to session creation.
- Create/Modify: `tests/chatSessionRepository_test.py` if existing repo test absent — assert `end_at` follows latest message timestamp.

## Task 1: Remove clarification `user_answer`

**Files:**
- Modify: `model/ClarificationQuestion.py:5-60`
- Modify: `repository/clarificationRepository.py:14-118`
- Modify: `tests/clarificationMechanism_test.py:87-106`

- [ ] **Step 1: Write failing model test**

Add after `test_clarification_question_has_no_ambiguous_phrase_column()` in `tests/clarificationMechanism_test.py`:

```python
def test_clarification_question_has_no_user_answer_column():
    """ClarificationQuestion no longer persists numeric user answer."""
    from model.ClarificationQuestion import ClarificationQuestion

    assert ClarificationQuestion.__table__.columns.get("user_answer") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_question_has_no_user_answer_column -v
```

Expected: FAIL because `user_answer` column exists.

- [ ] **Step 3: Remove ORM column and fallback**

In `model/ClarificationQuestion.py`, remove `Integer` import from:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
```

to:

```python
from sqlalchemy import Boolean, DateTime, ForeignKey, String
```

Remove column:

```python
user_answer: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

Change property:

```python
@property
def clarification_answer(self) -> str | None:
    return self.selected_answer
```

- [ ] **Step 4: Stop repository writes to `user_answer`**

In `repository/clarificationRepository.py`, remove from `ClarificationQuestion(...)`:

```python
user_answer=self._parse_user_answer(clarification_answer),
```

Remove from `update_with_answer()`:

```python
question.user_answer = self._parse_user_answer(clarification_answer)
```

Delete helper:

```python
@staticmethod
def _parse_user_answer(clarification_answer: str | None) -> int | None:
    if clarification_answer is None:
        return None
    try:
        return int(clarification_answer)
    except ValueError:
        return None
```

- [ ] **Step 5: Run targeted clarification tests**

Run:

```bash
pytest tests/clarificationMechanism_test.py::test_clarification_question_has_no_user_answer_column tests/clarificationMechanism_test.py::test_clarification_question_has_no_ambiguous_phrase_column -v
```

Expected: PASS.

## Task 2: Add Alembic migration for `user_answer`

**Files:**
- Create: `alembic/versions/f6a7b8c9d0e1_drop_user_answer_from_clarification_questions.py`

- [ ] **Step 1: Create migration file**

Create `alembic/versions/f6a7b8c9d0e1_drop_user_answer_from_clarification_questions.py` with:

```python
"""drop user_answer from clarification_questions

Revision ID: f6a7b8c9d0e1
Revises: c7d8e9f0a1b2
Create Date: 2026-05-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("clarification_questions", "user_answer")


def downgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("user_answer", sa.Integer(), nullable=True),
    )
```

- [ ] **Step 2: Check migration graph heads**

Run:

```bash
alembic heads
```

Expected: command succeeds. If multiple heads exist from current branch work, keep new migration chained to existing clarification branch `c7d8e9f0a1b2` unless project already has merge migration requiring different down revision.

## Task 3: Persist `chatbot_id` on chat session creation

**Files:**
- Modify: `service/chatSessionService.py:16-28`
- Modify: `service/chatService.py:70-78`
- Modify: `tests/chatPipeline_test.py:52-61`

- [ ] **Step 1: Write failing service test assertion**

In `tests/chatPipeline_test.py`, change `_create_chat_service()` active chatbot mock from:

```python
service._get_active_chatbot_for_role = AsyncMock(return_value=Mock(addon_prompt="Prompt awal."))
```

to:

```python
service._get_active_chatbot_for_role = AsyncMock(
    return_value=Mock(
        id=UUID("00000000-0000-0000-0000-000000000901"),
        addon_prompt="Prompt awal.",
    )
)
```

Add to `test_process_query_returns_clarification_when_query_is_ambiguous()` after process call:

```python
service.session_service.create_session_if_missing.assert_awaited_once_with(
    session_id=SESSION_CLARIFY,
    user_id="user-1",
    first_message="Siapa yang paling perform?",
    chatbot_id=UUID("00000000-0000-0000-0000-000000000901"),
)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/chatPipeline_test.py::test_process_query_returns_clarification_when_query_is_ambiguous -v
```

Expected: FAIL because `create_session_if_missing()` call lacks `chatbot_id`.

- [ ] **Step 3: Update session service signature**

In `service/chatSessionService.py`, change signature to:

```python
async def create_session_if_missing(
    self,
    session_id: UUID,
    user_id: UUID,
    first_message: str,
    chatbot_id: UUID | None = None,
) -> None:
```

Change repository call to:

```python
await self.session_repo.create(
    session_id=session_id,
    user_id=user_id,
    title=first_message[:80].strip() or "New Chat",
    chatbot_id=chatbot_id,
)
```

- [ ] **Step 4: Pass active chatbot ID from chat service**

In `service/chatService.py`, change session creation call to:

```python
await self.session_service.create_session_if_missing(
    session_id=session_id,
    user_id=user_id,
    first_message=user_message,
    chatbot_id=active_chatbot.id,
)
```

- [ ] **Step 5: Run targeted chat pipeline test**

Run:

```bash
pytest tests/chatPipeline_test.py::test_process_query_returns_clarification_when_query_is_ambiguous -v
```

Expected: PASS.

## Task 4: Keep `chat_sessions.end_at` equal to latest message timestamp

**Files:**
- Modify: `repository/chatSessionRepository.py:34-48`
- Test: `tests/chatSessionRepository_test.py`

- [ ] **Step 1: Locate or create repository test file**

If `tests/chatSessionRepository_test.py` does not exist, create it with imports matching project fixtures:

```python
from uuid import uuid4

import pytest

from model.ChatSession import ChatSession
from repository.chatSessionRepository import ChatSessionRepository
```

- [ ] **Step 2: Write failing repository test**

Add to `tests/chatSessionRepository_test.py`:

```python
@pytest.mark.asyncio
async def test_create_message_updates_session_end_at_to_message_send_at(db_session):
    session_id = uuid4()
    user_id = uuid4()
    session = ChatSession(
        session_id=session_id,
        user_id=user_id,
        session_name="Test session",
    )
    db_session.add(session)
    await db_session.flush()

    repo = ChatSessionRepository(db_session)
    message = await repo.create_message(
        session_id=session_id,
        message="Halo",
        is_sender_chatbot=False,
    )

    await db_session.refresh(session)
    assert session.end_at == message.send_at
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
pytest tests/chatSessionRepository_test.py::test_create_message_updates_session_end_at_to_message_send_at -v
```

Expected: FAIL because `end_at` remains `None`.

- [ ] **Step 4: Update repository create_message**

In `repository/chatSessionRepository.py`, change `create_message()` to:

```python
async def create_message(
    self,
    session_id: uuid.UUID,
    message: str,
    is_sender_chatbot: bool,
) -> ChatMessage:
    chat_message = ChatMessage(
        session_id=session_id,
        message=message,
        is_sender_chatbot=is_sender_chatbot,
    )
    self.db.add(chat_message)
    await self.db.flush()

    session = await self.get_by_id(session_id)
    if session is not None:
        session.end_at = chat_message.send_at
        await self.db.flush()

    await self.db.refresh(chat_message)
    return chat_message
```

- [ ] **Step 5: Run repository test**

Run:

```bash
pytest tests/chatSessionRepository_test.py::test_create_message_updates_session_end_at_to_message_send_at -v
```

Expected: PASS.

## Task 5: Final verification

**Files:**
- Verify changed tests and migration syntax.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/chatPipeline_test.py::test_process_query_returns_clarification_when_query_is_ambiguous tests/clarificationMechanism_test.py::test_clarification_question_has_no_user_answer_column tests/clarificationMechanism_test.py::test_clarification_question_has_no_ambiguous_phrase_column tests/chatSessionRepository_test.py::test_create_message_updates_session_end_at_to_message_send_at -v
```

Expected: PASS.

- [ ] **Step 2: Run broader related tests**

Run:

```bash
pytest tests/chatPipeline_test.py tests/chatStreaming_test.py tests/clarificationMechanism_test.py -v
```

Expected: PASS, or only failures unrelated to these changes documented with exact failing test names.

- [ ] **Step 3: Inspect diff**

Run:

```bash
git diff -- model/ClarificationQuestion.py repository/clarificationRepository.py service/chatSessionService.py service/chatService.py repository/chatSessionRepository.py tests/clarificationMechanism_test.py tests/chatPipeline_test.py tests/chatSessionRepository_test.py alembic/versions/f6a7b8c9d0e1_drop_user_answer_from_clarification_questions.py
```

Expected: diff only contains requested cleanup and session timestamp/chatbot fixes.

## Self-Review

- Spec coverage: Task 1 removes model/repository `user_answer`; Task 2 adds migration; Task 3 persists `chatbot_id`; Task 4 updates `end_at`; Task 5 verifies.
- Placeholder scan: no TBD/TODO/fill later placeholders.
- Type consistency: `chatbot_id` uses `UUID | None`; session ID constants use `UUID`; `end_at` uses `ChatMessage.send_at` datetime.
