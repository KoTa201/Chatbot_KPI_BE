# Runtime Utils Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract repeated runtime helper functions into focused `utils/` modules without changing business logic or moving schemas.

**Architecture:** Add small helper modules under existing `utils/` package for pagination, UTC time, and JSON responses. Replace duplicate controller/service/middleware call sites with imports while preserving existing status codes, response shapes, and validation behavior.

**Tech Stack:** Python 3.10, FastAPI/Starlette, SQLAlchemy async, pytest.

---

## File Structure

- Create `utils/pagination.py`: controller-safe pagination validation and total-page calculation.
- Create `utils/datetime.py`: canonical UTC timestamp function.
- Create `utils/responses.py`: JSON `Response` builder used by middleware.
- Modify `controller/chatbotController.py`: use pagination validators.
- Modify `controller/userController.py`: use pagination validators.
- Modify `controller/kpiGroupController.py`: use pagination validators and total-page helper.
- Modify `controller/ingestionLogController.py`: use pagination validators while preserving 400 behavior and local defaults.
- Modify `service/chatbotService.py`: use total-page helper while preserving `max(1, ...)` behavior for zero totals.
- Modify `middleware/jwtMiddleware.py`: replace local `_json_response()` with shared helper.
- Modify safe UTC runtime call sites only where a zero-argument replacement preserves behavior:
  - `model/ChatMessage.py`
  - `model/ChatSession.py`
  - `model/ClarificationQuestion.py`
  - `model/RevokedToken.py`
  - `model/User.py`
  - `repository/chatSessionRepository.py`
  - `repository/userRepository.py`
  - `service/authService.py`
  - `service/schedulerJobService.py`

Do not move `PaginationInfo` schemas or domain constants.

---

### Task 1: Add pagination utilities

**Files:**
- Create: `utils/pagination.py`
- Test: none new; existing controller tests cover behavior.

- [ ] **Step 1: Create pagination utility module**

Create `utils/pagination.py` with exact content:

```python
import math


def validate_page(page: int) -> int:
    if not isinstance(page, int):
        raise ValueError(f"page harus berupa integer. Diterima: {type(page).__name__}")
    if page < 1:
        raise ValueError("'page' tidak boleh negatif dan minimal 1.")
    return page


def validate_limit(limit: int, *, max_limit: int = 100, clamp: bool = False) -> int:
    if not isinstance(limit, int):
        raise ValueError(f"limit harus berupa integer. Diterima: {type(limit).__name__}")
    if limit < 1:
        raise ValueError("'limit' harus antara 1 dan 100.")
    if limit > max_limit:
        if clamp:
            return max_limit
        raise ValueError(f"'limit' harus antara 1 dan {max_limit}.")
    return limit


def calculate_total_pages(total: int, limit: int, *, minimum: int = 0) -> int:
    if total <= 0:
        return minimum
    return math.ceil(total / limit)
```

- [ ] **Step 2: Compile utility module**

Run:

```bash
python -m py_compile utils/pagination.py
```

Expected: command exits 0 with no output.

- [ ] **Step 3: Commit pagination utility**

```bash
git add utils/pagination.py
git commit -m "refactor: add pagination utilities"
```

---

### Task 2: Replace controller pagination duplication

**Files:**
- Modify: `controller/chatbotController.py:3-45`
- Modify: `controller/userController.py:8-64`
- Modify: `controller/kpiGroupController.py:5-64`
- Modify: `controller/ingestionLogController.py:13-144`
- Test: `tests/chatbotManagement_test.py`
- Test: `tests/userManagement_test.py`

- [ ] **Step 1: Update `controller/chatbotController.py` imports**

Remove unused imports `Depends`, `HTTPException`, `status`, `Session`, and `get_db`. Add pagination helpers.

Expected import block:

```python
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from model.Chatbot import AuthorityEnum
from schema.chatbotSchema import (
    ChatbotCreate,
    ChatbotUpdate,
    ChatbotListResponse,
    ChatbotResponse,
    MessageResponse,
)
from service.chatbotService import ChatbotService
from utils.pagination import validate_limit, validate_page
```

- [ ] **Step 2: Update `ChatbotController.list_chatbots()` validation**

Replace lines checking `limit` and `page` with:

```python
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
```

Keep `from fastapi import HTTPException, status` if this block uses them. Final imports should include:

```python
from fastapi import HTTPException, status
```

- [ ] **Step 3: Update `controller/userController.py` imports**

Add:

```python
from utils.pagination import validate_limit, validate_page
```

Keep existing `HTTPException, status` import because validation still raises `HTTPException`.

- [ ] **Step 4: Update `UserController.get_all_users()` validation**

Replace duplicated `limit` and `page` checks with:

```python
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
```

- [ ] **Step 5: Update `controller/kpiGroupController.py` imports**

Remove `import math`. Add:

```python
from utils.pagination import calculate_total_pages, validate_limit, validate_page
```

- [ ] **Step 6: Update `KPIGroupController.list_groups()` validation and total pages**

Replace duplicated validation with:

```python
        try:
            page = validate_page(page)
            limit = validate_limit(limit)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            )
```

Replace total pages expression with:

```python
            total_pages=calculate_total_pages(total, limit),
```

- [ ] **Step 7: Update `controller/ingestionLogController.py` imports**

Add:

```python
from utils.pagination import validate_limit, validate_page
```

Keep `DEFAULT_LIMIT`, `MAX_LIMIT`, and `VALID_GROUP_TYPES` local.

- [ ] **Step 8: Update `IngestionLogController.get_ingestion_logs()` validation**

Replace calls to local static methods with shared helpers while preserving clamp behavior and status code 400:

```python
        try:
            page = validate_page(page)
            limit = validate_limit(limit, max_limit=MAX_LIMIT, clamp=True)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )
```

- [ ] **Step 9: Remove local static validators from ingestion log controller**

Delete `_validate_limit()` and `_validate_page()` methods from `controller/ingestionLogController.py`.

- [ ] **Step 10: Run focused pagination tests**

Run:

```bash
pytest tests/chatbotManagement_test.py::TestChatbotList -v
pytest tests/userManagement_test.py::TestUserManagement::test_get_all_users_pagination -v
```

If node IDs differ, run full files:

```bash
pytest tests/chatbotManagement_test.py tests/userManagement_test.py -v
```

Expected: tests pass or any failures are unrelated existing fixture/setup problems documented in final summary.

- [ ] **Step 11: Commit controller pagination refactor**

```bash
git add controller/chatbotController.py controller/userController.py controller/kpiGroupController.py controller/ingestionLogController.py
git commit -m "refactor: reuse pagination helpers in controllers"
```

---

### Task 3: Replace total-page duplication in chatbot service

**Files:**
- Modify: `service/chatbotService.py:1-64`
- Test: `tests/chatbotManagement_test.py`

- [ ] **Step 1: Update service import**

Add:

```python
from utils.pagination import calculate_total_pages
```

- [ ] **Step 2: Replace ceiling division**

Replace:

```python
        total_pages = max(1, -(-total // limit))  # ceiling division
```

with:

```python
        total_pages = calculate_total_pages(total, limit, minimum=1)
```

- [ ] **Step 3: Run chatbot tests**

Run:

```bash
pytest tests/chatbotManagement_test.py -v
```

Expected: pass.

- [ ] **Step 4: Commit service page math refactor**

```bash
git add service/chatbotService.py
git commit -m "refactor: reuse total pages helper"
```

---

### Task 4: Add response utility and update JWT middleware

**Files:**
- Create: `utils/responses.py`
- Modify: `middleware/jwtMiddleware.py:1-118`
- Test: `tests/userManagement_test.py`

- [ ] **Step 1: Create response utility module**

Create `utils/responses.py` with exact content:

```python
import json

from starlette.responses import Response


def json_response(status_code: int, detail: str) -> Response:
    body = json.dumps({"detail": detail}, ensure_ascii=False)
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
    )
```

- [ ] **Step 2: Update JWT middleware imports**

Remove `import json`. Add:

```python
from utils.responses import json_response
```

- [ ] **Step 3: Replace local helper calls**

In `middleware/jwtMiddleware.py`, replace every `_json_response(` call with `json_response(`.

- [ ] **Step 4: Delete local helper**

Remove function:

```python
def _json_response(status_code: int, detail: str) -> Response:
    body = json.dumps({"detail": detail}, ensure_ascii=False)
    return Response(
        content=body,
        status_code=status_code,
        media_type="application/json",
    )
```

Keep `Response` import if type annotations still use it in `dispatch()`.

- [ ] **Step 5: Run auth/user tests**

Run:

```bash
pytest tests/userManagement_test.py -v
```

Expected: pass.

- [ ] **Step 6: Commit response utility refactor**

```bash
git add utils/responses.py middleware/jwtMiddleware.py
git commit -m "refactor: share JSON response helper"
```

---

### Task 5: Add UTC datetime utility and update safe call sites

**Files:**
- Create: `utils/datetime.py`
- Modify: `model/ChatMessage.py`
- Modify: `model/ChatSession.py`
- Modify: `model/ClarificationQuestion.py`
- Modify: `model/RevokedToken.py`
- Modify: `model/User.py`
- Modify: `repository/chatSessionRepository.py`
- Modify: `repository/userRepository.py`
- Modify: `service/authService.py`
- Modify: `service/schedulerJobService.py`
- Test: `tests/chatPipeline_test.py`, `tests/userManagement_test.py`, `tests/scheduler_test.py`

- [ ] **Step 1: Create datetime utility module**

Create `utils/datetime.py` with exact content:

```python
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
```

- [ ] **Step 2: Update SQLAlchemy model defaults**

For each model below, import `utc_now` and replace zero-argument lambdas:

```python
from utils.datetime import utc_now
```

Replace:

```python
default=lambda: datetime.now(timezone.utc)
```

with:

```python
default=utc_now
```

Replace in `model/User.py`:

```python
onupdate=lambda: datetime.now(timezone.utc)
```

with:

```python
onupdate=utc_now
```

Apply to:

- `model/ChatMessage.py`
- `model/ChatSession.py`
- `model/ClarificationQuestion.py`
- `model/RevokedToken.py`
- `model/User.py`

Remove unused `timezone` imports from those files. Remove unused `datetime` imports only if type annotations do not need `datetime`.

- [ ] **Step 3: Update repository runtime timestamps**

In `repository/chatSessionRepository.py`, import `utc_now` and replace:

```python
session.end_at = datetime.now(timezone.utc)
```

with:

```python
session.end_at = utc_now()
```

In `repository/userRepository.py`, import `utc_now` and replace:

```python
now = datetime.now(timezone.utc)
```

with:

```python
now = utc_now()
```

Replace:

```python
record.used_at = datetime.now(timezone.utc)
```

with:

```python
record.used_at = utc_now()
```

Remove unused `timezone` imports. Keep `datetime` imports if used in type annotations.

- [ ] **Step 4: Update auth service token timestamps**

In `service/authService.py`, import `utc_now` and replace all `datetime.now(timezone.utc)` token/reset timestamp expressions with `utc_now()`.

Examples:

```python
expire_at = utc_now() + timedelta(seconds=expire_seconds)
```

```python
expires_at = utc_now() + timedelta(minutes=reset_expire_minutes)
```

Remove unused `timezone` import if no longer used.

- [ ] **Step 5: Update scheduler job runtime timestamps**

In `service/schedulerJobService.py`, import `utc_now` and replace:

```python
last_run_at=datetime.now(timezone.utc)
now = datetime.now(timezone.utc)
return job.trigger.get_next_fire_time(None, datetime.now(timezone.utc))
```

with:

```python
last_run_at=utc_now()
now = utc_now()
return job.trigger.get_next_fire_time(None, utc_now())
```

Remove unused `timezone` import if no longer used.

- [ ] **Step 6: Compile changed Python files**

Run:

```bash
python -m py_compile utils/datetime.py model/ChatMessage.py model/ChatSession.py model/ClarificationQuestion.py model/RevokedToken.py model/User.py repository/chatSessionRepository.py repository/userRepository.py service/authService.py service/schedulerJobService.py
```

Expected: command exits 0.

- [ ] **Step 7: Run focused timestamp-related tests**

Run:

```bash
pytest tests/chatPipeline_test.py tests/userManagement_test.py tests/scheduler_test.py -v
```

Expected: pass.

- [ ] **Step 8: Commit datetime utility refactor**

```bash
git add utils/datetime.py model/ChatMessage.py model/ChatSession.py model/ClarificationQuestion.py model/RevokedToken.py model/User.py repository/chatSessionRepository.py repository/userRepository.py service/authService.py service/schedulerJobService.py
git commit -m "refactor: share UTC timestamp helper"
```

---

### Task 6: Final verification and duplicate scan

**Files:**
- Inspect only: changed files
- Test: full suite if feasible

- [ ] **Step 1: Search remaining duplicate pagination logic**

Run:

```bash
python - <<'PY'
from pathlib import Path
patterns = ["limit < 1 or limit > 100", "page < 1", "-(-total // limit)", "math.ceil(total / limit)"]
for p in Path('.').rglob('*.py'):
    if '.venv' in p.parts:
        continue
    text = p.read_text(encoding='utf-8')
    for pattern in patterns:
        if pattern in text:
            print(f"{p}: {pattern}")
PY
```

Expected: no matches in runtime app code except tests or unrelated code.

- [ ] **Step 2: Search remaining direct UTC now runtime calls**

Run:

```bash
python - <<'PY'
from pathlib import Path
for p in Path('.').rglob('*.py'):
    if '.venv' in p.parts or 'tests' in p.parts:
        continue
    text = p.read_text(encoding='utf-8')
    if 'datetime.now(timezone.utc)' in text:
        print(p)
PY
```

Expected: no matches in intended safe-refactor files. If matches remain in files outside plan scope, leave them and mention them.

- [ ] **Step 3: Run full test suite**

Run:

```bash
pytest
```

Expected: pass. If environment prevents full suite, record exact failure/timeout and focused test results.

- [ ] **Step 4: Review final diff**

Run:

```bash
git diff --stat HEAD~5..HEAD
git status --short
```

Expected: only intended files changed. Existing pre-task modifications may still appear:

```text
 M service/chatService.py
 M service/llmService.py
?? graphify-out/
```

Do not stage or modify those pre-existing files unless they were intentionally changed by implementation.

- [ ] **Step 5: Final summary**

Report:

- Created files: `utils/pagination.py`, `utils/responses.py`, `utils/datetime.py`
- Moved functions: pagination validation/page math, JSON response builder, UTC now helper
- Simplified files: controllers, JWT middleware, selected timestamp call sites
- Tests run and results

---

## Self-Review

Spec coverage:
- Runtime helper extraction covered by Tasks 1, 4, 5.
- Pagination checks/page math covered by Tasks 1-3.
- JSON response helper covered by Task 4.
- UTC timestamp helper covered by Task 5.
- Non-goals preserved: no schema move, no domain constants move, no business logic refactor.

Placeholder scan: no TBD/TODO/fill-later placeholders.

Type consistency:
- `validate_page(page: int) -> int`, `validate_limit(limit: int, *, max_limit: int = 100, clamp: bool = False) -> int`, `calculate_total_pages(total: int, limit: int, *, minimum: int = 0) -> int`, `json_response(status_code: int, detail: str) -> Response`, and `utc_now() -> datetime` are used consistently across tasks.
