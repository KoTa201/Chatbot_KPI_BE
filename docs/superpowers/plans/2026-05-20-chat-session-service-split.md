# Chat Session Service Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move chat session lifecycle behavior from `ChatService` into a new `ChatSessionService` while keeping chat ask/answer endpoints unchanged.

**Architecture:** `ChatService` remains the RAG pipeline orchestrator and delegates session creation to `ChatSessionService`. `ChatSessionService` owns session repository access, user ownership checks, and session CRUD methods used by controller session endpoints.

**Tech Stack:** FastAPI, SQLAlchemy async sessions, Python service/repository pattern, pytest.

---

## File structure

- Create: `service/chatSessionService.py` — session-domain service for create-if-missing, list, delete, and title updates.
- Modify: `service/chatService.py` — remove session CRUD methods and use `ChatSessionService` for session creation in `process_query()`.
- Modify: `controller/chatController.py` — route session endpoint handlers through `ChatSessionService` instead of `ChatService`.
- Test: use import smoke checks and existing schema/chatbot tests.

---

### Task 1: Add ChatSessionService

**Files:**
- Create: `service/chatSessionService.py`

- [ ] **Step 1: Write the service file**

Create `service/chatSessionService.py` with this content:

```python
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from repository.chatSessionRepository import ChatSessionRepository


class ChatSessionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.session_repo = ChatSessionRepository(db)

    async def create_session_if_missing(
        self,
        session_id: str,
        user_id: str,
        first_message: str,
    ) -> None:
        existing = await self.session_repo.get_by_id(session_id)
        if existing is None:
            await self.session_repo.create(
                session_id=session_id,
                user_id=user_id,
                title=first_message[:80].strip() or "New Chat",
            )

    async def get_sessions(self, user_id: str) -> list:
        return await self.session_repo.get_by_user(user_id=user_id)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.session_repo.delete(session_id)
        await self.db.flush()

    async def update_session_title(
        self,
        session_id: str,
        user_id: str,
        title: str,
    ):
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        updated = await self.session_repo.update_title(session_id, title)
        await self.db.flush()
        return updated
```

- [ ] **Step 2: Run import check**

Run:

```bash
python - <<'PY'
from service.chatSessionService import ChatSessionService
print(ChatSessionService.__name__)
PY
```

Expected output:

```text
ChatSessionService
```

---

### Task 2: Make ChatService delegate session creation only

**Files:**
- Modify: `service/chatService.py`

- [ ] **Step 1: Add ChatSessionService import**

In `service/chatService.py`, add this import near the other service imports:

```python
from service.chatSessionService import ChatSessionService
```

- [ ] **Step 2: Replace `self.session_repo` with `self.session_service`**

In `ChatService.__init__`, replace:

```python
        self.session_repo = ChatSessionRepository(db)
```

with:

```python
        self.session_service = ChatSessionService(db)
```

- [ ] **Step 3: Remove unused ChatSessionRepository import**

Delete this import from `service/chatService.py`:

```python
from repository.chatSessionRepository import ChatSessionRepository
```

- [ ] **Step 4: Remove `create_session` method**

Delete this method from `ChatService`:

```python
    async def create_session(
        self, session_id: str, user_id: str, first_message: str
    ) -> None:
        existing = await self.session_repo.get_by_id(session_id)
        if existing is None:
            await self.session_repo.create(
                session_id=session_id,
                user_id=user_id,
                title=first_message[:80].strip() or "New Chat",
            )
```

- [ ] **Step 5: Delegate session creation in `process_query`**

Replace this block in `process_query()`:

```python
        await self.create_session(
            session_id=session_id,
            user_id=user_id,
            first_message=user_message,
        )
```

with:

```python
        await self.session_service.create_session_if_missing(
            session_id=session_id,
            user_id=user_id,
            first_message=user_message,
        )
```

- [ ] **Step 6: Remove session CRUD methods from ChatService**

Delete these methods from `ChatService`:

```python
    async def get_sessions(self, user_id: str) -> list:
        return await self.session_repo.get_by_user(user_id=user_id)

    async def delete_session(self, session_id: str, user_id: str) -> None:
        from fastapi import HTTPException, status
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.session_repo.delete(session_id)
        await self.db.flush()

    async def update_session_title(
        self, session_id: str, user_id: str, title: str
    ):
        from fastapi import HTTPException, status
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        updated = await self.session_repo.update_title(session_id, title)
        await self.db.flush()
        return updated
```

- [ ] **Step 7: Run ChatService import smoke test**

Run:

```bash
python - <<'PY'
from service.chatService import ChatService
print(ChatService.__name__)
PY
```

Expected output:

```text
ChatService
```

---

### Task 3: Route controller session endpoints to ChatSessionService

**Files:**
- Modify: `controller/chatController.py`

- [ ] **Step 1: Add ChatSessionService import**

Add this import near the existing service imports:

```python
from service.chatSessionService import ChatSessionService
```

- [ ] **Step 2: Update `handle_get_sessions`**

Replace:

```python
        service = ChatService(self.db)
        sessions = await service.get_sessions(user_id=user_id)
```

with:

```python
        service = ChatSessionService(self.db)
        sessions = await service.get_sessions(user_id=user_id)
```

- [ ] **Step 3: Update `handle_delete_session`**

Replace:

```python
        service = ChatService(self.db)
        await service.delete_session(session_id=session_id, user_id=user_id)
```

with:

```python
        service = ChatSessionService(self.db)
        await service.delete_session(session_id=session_id, user_id=user_id)
```

- [ ] **Step 4: Update `handle_update_session_title`**

Replace:

```python
        service = ChatService(self.db)
        updated = await service.update_session_title(
```

with:

```python
        service = ChatSessionService(self.db)
        updated = await service.update_session_title(
```

- [ ] **Step 5: Run controller import smoke test**

Run:

```bash
python - <<'PY'
from controller.chatController import ChatController
print(ChatController.__name__)
PY
```

Expected output:

```text
ChatController
```

---

### Task 4: Verify service split

**Files:**
- Test: `tests/chat_schema_replacement_test.py`
- Existing smoke checks

- [ ] **Step 1: Run schema test**

Run:

```bash
pytest tests/chat_schema_replacement_test.py -v
```

Expected: 4 passed.

- [ ] **Step 2: Run combined import smoke test**

Run:

```bash
python - <<'PY'
from service.chatService import ChatService
from service.chatSessionService import ChatSessionService
from controller.chatController import ChatController
print(ChatService.__name__)
print(ChatSessionService.__name__)
print(ChatController.__name__)
PY
```

Expected output:

```text
ChatService
ChatSessionService
ChatController
```

- [ ] **Step 3: Run chatbot management regression test**

Run:

```bash
pytest tests/chatbotManagement_test.py -v
```

Expected: the same 3 baseline failures unrelated to this refactor may remain:

- `TestListChatbot.test_list_inactive_included`
- `TestUpdateChatbot.test_update_addon_prompt_to_null`
- `TestSoftDeleteChatbot.test_soft_delete_still_in_list`

No new import or chat session service errors should appear.

- [ ] **Step 4: Check working tree**

Run:

```bash
git status --short
```

Expected: changed files include `service/chatSessionService.py`, `service/chatService.py`, and `controller/chatController.py` plus existing schema replacement files.

---

## Self-review

Spec coverage:

- New `ChatSessionService` owns session lifecycle and ownership checks: Task 1.
- `ChatService` focuses on ask/answer pipeline and delegates session creation: Task 2.
- `ChatController` session endpoints use `ChatSessionService`: Task 3.
- API routes and schemas unchanged: no router/schema changes in plan.
- Verification covers imports, schema test, and known baseline regression suite: Task 4.

Placeholder scan: no placeholders or open-ended implementation steps remain.

Type consistency: all planned methods use `user_id: str`, matching current `ChatController` and `ChatService` usage in this worktree.
