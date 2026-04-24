# Chat Session Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `chat_sessions` table and three new endpoints (list, delete, rename) so users can manage their own chat sessions.

**Architecture:** A new `ChatSession` ORM model + `ChatSessionRepository` slots into the existing Router → Controller → Service → Repository pattern. Session auto-creation is injected at the top of `process_query()`. Hard-delete is handled at the application level: the service deletes audit logs and clarification logs for the session before removing the session row (no DB-level FK cascade, which avoids a complex data migration).

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, PostgreSQL, Pydantic v2

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `alembic/versions/014_create_chat_sessions.py` | DB migration — new table |
| Create | `model/ChatSession.py` | ORM model for `chat_sessions` |
| Modify | `model/__init__.py` | Export ChatSession |
| Modify | `model/User.py` | Add `sessions` relationship |
| Create | `schema/sessionSchema.py` | Pydantic request/response schemas |
| Create | `repository/chatSessionRepository.py` | CRUD for `chat_sessions` |
| Modify | `repository/chatbotAuditLogRepository.py` | Add `delete_by_session()` |
| Modify | `repository/clarificationRepository.py` | Add `delete_by_session()` |
| Modify | `service/chatService.py` | Auto-create session + 3 management methods |
| Modify | `controller/chatController.py` | 3 new handlers |
| Modify | `router/chatRouter.py` | 3 new routes |

---

## Task 1: Alembic Migration — Create `chat_sessions` Table

**Files:**
- Create: `alembic/versions/014_create_chat_sessions.py`

- [ ] **Step 1: Create the migration file**

```python
"""Create chat_sessions table

Revision ID: 014_create_chat_sessions
Revises: 013_scheduler_monthly_cron
Create Date: 2026-04-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "014_create_chat_sessions"
down_revision: Union[str, None] = "013_scheduler_monthly_cron"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
```

- [ ] **Step 2: Run the migration**

```bash
cd Chatbot_KPI_BE
alembic upgrade head
```

Expected output ends with: `Running upgrade 013_scheduler_monthly_cron -> 014_create_chat_sessions`

- [ ] **Step 3: Commit**

```bash
rtk git add alembic/versions/014_create_chat_sessions.py
rtk git commit -m "feat: add chat_sessions migration"
```

---

## Task 2: ORM Model — `model/ChatSession.py`

**Files:**
- Create: `model/ChatSession.py`

- [ ] **Step 1: Create the model file**

```python
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from databaseConfig import Base

if TYPE_CHECKING:
    from model.User import UserORM


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["UserORM"] = relationship(
        "UserORM", back_populates="sessions", lazy="noload"
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} title={self.title!r} user={self.user_id}>"
```

- [ ] **Step 2: Commit**

```bash
rtk git add model/ChatSession.py
rtk git commit -m "feat: add ChatSession ORM model"
```

---

## Task 3: Wire Model Into `model/__init__.py` and `model/User.py`

**Files:**
- Modify: `model/__init__.py`
- Modify: `model/User.py`

- [ ] **Step 1: Add ChatSession to `model/__init__.py`**

Open `model/__init__.py`. It currently ends at line 8 (blank line after `SchedulerConfigORM`). Add:

```python
from .ChatSession import ChatSession
```

Full file after edit:
```python
from .User import UserORM
from .KPITracker import KPITrackerORM
from .KPIGroup import KPIGroupORM
from .IngestionLog import IngestionLogORM
from .Chatbot import Chatbot
from .ChatbotAuditLog import ChatbotAuditLog
from .KPIMaster import KPIMasterORM
from .SchedulerConfig import SchedulerConfigORM
from .ChatSession import ChatSession
```

- [ ] **Step 2: Add `sessions` relationship to `model/User.py`**

In `model/User.py`, add `ChatSession` to the `TYPE_CHECKING` block and add the relationship.

In the `TYPE_CHECKING` block (currently lines 16-17), add:
```python
if TYPE_CHECKING:
    from model.ChatbotAuditLog import ChatbotAuditLog
    from model.PasswordReset import PasswordResetORM
    from model.ChatSession import ChatSession
```

In `UserORM` class, after the `audit_logs` relationship (currently line 58-60), add:
```python
    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="user", lazy="noload"
    )
```

- [ ] **Step 3: Commit**

```bash
rtk git add model/__init__.py model/User.py
rtk git commit -m "feat: wire ChatSession into model registry and User relationship"
```

---

## Task 4: Pydantic Schemas — `schema/sessionSchema.py`

**Files:**
- Create: `schema/sessionSchema.py`

- [ ] **Step 1: Create the schema file**

```python
from datetime import datetime
from pydantic import BaseModel, field_validator


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateSessionTitleRequest(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def title_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title tidak boleh kosong.")
        if len(v) > 255:
            raise ValueError("Title terlalu panjang, maksimal 255 karakter.")
        return v
```

- [ ] **Step 2: Commit**

```bash
rtk git add schema/sessionSchema.py
rtk git commit -m "feat: add session Pydantic schemas"
```

---

## Task 5: Repository — `repository/chatSessionRepository.py`

**Files:**
- Create: `repository/chatSessionRepository.py`

- [ ] **Step 1: Create the repository file**

```python
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from model.ChatSession import ChatSession


class ChatSessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, session_id: str, user_id: str, title: str) -> ChatSession:
        session = ChatSession(
            id=session_id,
            user_id=uuid.UUID(user_id),
            title=title[:80].strip() or "New Chat",
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_user(self, user_id: str) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == uuid.UUID(user_id))
            .order_by(ChatSession.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: str) -> Optional[ChatSession]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_title(self, session_id: str, title: str) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.title = title
        session.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def delete(self, session_id: str) -> bool:
        session = await self.get_by_id(session_id)
        if session is None:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True
```

- [ ] **Step 2: Commit**

```bash
rtk git add repository/chatSessionRepository.py
rtk git commit -m "feat: add ChatSessionRepository"
```

---

## Task 6: Add `delete_by_session` to Existing Repositories

**Files:**
- Modify: `repository/chatbotAuditLogRepository.py`
- Modify: `repository/clarificationRepository.py`

- [ ] **Step 1: Add `delete_by_session` to `repository/chatbotAuditLogRepository.py`**

Add this import at the top of the file (after existing imports):
```python
from sqlalchemy import select, delete
```

Add this method at the end of the `AuditLogRepository` class:
```python
    async def delete_by_session(self, session_id: str) -> int:
        result = await self.db.execute(
            delete(ChatbotAuditLog).where(ChatbotAuditLog.session_id == session_id)
        )
        return result.rowcount
```

- [ ] **Step 2: Add `delete_by_session` to `repository/clarificationRepository.py`**

Add this import at the top of the file (after existing imports):
```python
from sqlalchemy import desc, select, delete
```

Add this method at the end of the `ClarificationRepository` class:
```python
    async def delete_by_session(self, session_id: str) -> int:
        result = await self.db.execute(
            delete(ClarificationLogORM).where(ClarificationLogORM.session_id == session_id)
        )
        return result.rowcount
```

- [ ] **Step 3: Commit**

```bash
rtk git add repository/chatbotAuditLogRepository.py repository/clarificationRepository.py
rtk git commit -m "feat: add delete_by_session to audit and clarification repositories"
```

---

## Task 7: Session Management Methods in `service/chatService.py`

**Files:**
- Modify: `service/chatService.py`

- [ ] **Step 1: Add imports at the top of `service/chatService.py`**

After the existing imports (after line `from repository.chatbotAuditLogRepository import AuditLogRepository`), add:
```python
from repository.chatSessionRepository import ChatSessionRepository
from repository.clarificationRepository import ClarificationRepository
```

- [ ] **Step 2: Add `session_repo` to `ChatService.__init__`**

The current `__init__` is:
```python
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_repo = AuditLogRepository(db)
```

Change it to:
```python
    def __init__(self, db: AsyncSession):
        self.db = db
        self.audit_repo = AuditLogRepository(db)
        self.session_repo = ChatSessionRepository(db)
        self.clarification_repo = ClarificationRepository(db)
```

- [ ] **Step 3: Add `create_session` method to `ChatService`**

Add this method after `__init__`:
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

- [ ] **Step 4: Call `create_session` at the top of `process_query()`**

In `process_query()`, the current line 60 is:
```python
        session_id = session_id or str(uuid.uuid4())
```

Add the `create_session` call immediately after it:
```python
        session_id = session_id or str(uuid.uuid4())
        await self.create_session(
            session_id=session_id,
            user_id=user_id,
            first_message=user_message,
        )
```

- [ ] **Step 5: Add `get_sessions` method to `ChatService`**

Add at the end of the `ChatService` class (after `get_audit_history`):
```python
    async def get_sessions(self, user_id: str) -> list:
        return await self.session_repo.get_by_user(user_id=user_id)
```

- [ ] **Step 6: Add `delete_session` method to `ChatService`**

```python
    async def delete_session(self, session_id: str, user_id: str) -> None:
        from fastapi import HTTPException, status
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session tidak ditemukan.",
            )
        if str(session.user_id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.clarification_repo.delete_by_session(session_id)
        await self.audit_repo.delete_by_session(session_id)
        await self.session_repo.delete(session_id)
        await self.db.flush()
```

- [ ] **Step 7: Add `update_session_title` method to `ChatService`**

```python
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
        if str(session.user_id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        updated = await self.session_repo.update_title(session_id, title)
        await self.db.flush()
        return updated
```

- [ ] **Step 8: Commit**

```bash
rtk git add service/chatService.py
rtk git commit -m "feat: add session management methods and auto-create session in process_query"
```

---

## Task 8: Handlers in `controller/chatController.py`

**Files:**
- Modify: `controller/chatController.py`

- [ ] **Step 1: Add schema import**

At the top of `controller/chatController.py`, after the existing imports, add:
```python
from schema.sessionSchema import SessionResponse, UpdateSessionTitleRequest
```

- [ ] **Step 2: Add `handle_get_sessions` to `ChatController`**

Add at the end of the `ChatController` class:
```python
    async def handle_get_sessions(
        self,
        current_user: UserORM = Depends(get_current_user),
    ) -> list[SessionResponse]:
        user_id = str(current_user.id)
        service = ChatService(self.db)
        sessions = await service.get_sessions(user_id=user_id)
        return [SessionResponse.model_validate(s) for s in sessions]
```

- [ ] **Step 3: Add `handle_delete_session` to `ChatController`**

```python
    async def handle_delete_session(
        self,
        session_id: str,
        current_user: UserORM = Depends(get_current_user),
    ) -> None:
        user_id = str(current_user.id)
        service = ChatService(self.db)
        await service.delete_session(session_id=session_id, user_id=user_id)
```

- [ ] **Step 4: Add `handle_update_session_title` to `ChatController`**

```python
    async def handle_update_session_title(
        self,
        session_id: str,
        request: UpdateSessionTitleRequest,
        current_user: UserORM = Depends(get_current_user),
    ) -> SessionResponse:
        user_id = str(current_user.id)
        service = ChatService(self.db)
        updated = await service.update_session_title(
            session_id=session_id,
            user_id=user_id,
            title=request.title,
        )
        return SessionResponse.model_validate(updated)
```

- [ ] **Step 5: Commit**

```bash
rtk git add controller/chatController.py
rtk git commit -m "feat: add session management handlers to ChatController"
```

---

## Task 9: Routes in `router/chatRouter.py`

**Files:**
- Modify: `router/chatRouter.py`

- [ ] **Step 1: Add schema import**

At the top of `router/chatRouter.py`, after the existing imports, add:
```python
from schema.sessionSchema import SessionResponse, UpdateSessionTitleRequest
```

- [ ] **Step 2: Register three new routes in `setup_routes()`**

At the end of the `setup_routes()` method (after the `/audit/failed` route block), add:

```python
        # ── Sessions ────────────────────────────────────────────────── #
        self.router.add_api_route(
            "/sessions",
            self.get_sessions,
            methods=["GET"],
            response_model=list[SessionResponse],
            status_code=status.HTTP_200_OK,
            summary="Daftar semua session milik user yang sedang login",
        )

        self.router.add_api_route(
            "/sessions/{session_id}",
            self.delete_session,
            methods=["DELETE"],
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Hapus session beserta semua pesannya",
        )

        self.router.add_api_route(
            "/sessions/{session_id}/title",
            self.update_session_title,
            methods=["PATCH"],
            response_model=SessionResponse,
            status_code=status.HTTP_200_OK,
            summary="Ubah judul session",
        )
```

- [ ] **Step 3: Add the three handler methods to `ChatRouter`**

Add these after `get_failed_wireguard_logs`:

```python
    async def get_sessions(
        self,
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """Kembalikan semua session chatbot milik user yang sedang login."""
        return await controller.handle_get_sessions(current_user=current_user)

    async def delete_session(
        self,
        session_id: str,
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Hapus session beserta seluruh pesan dan clarification log-nya.
        Hanya pemilik session yang dapat melakukan ini.
        """
        await controller.handle_delete_session(
            session_id=session_id, current_user=current_user
        )

    async def update_session_title(
        self,
        session_id: str,
        request: UpdateSessionTitleRequest,
        current_user: UserORM = Depends(get_current_user),
        controller: ChatController = Depends(ChatController),
    ):
        """
        Ubah judul session. Hanya pemilik session yang dapat melakukan ini.
        """
        return await controller.handle_update_session_title(
            session_id=session_id, request=request, current_user=current_user
        )
```

- [ ] **Step 4: Commit**

```bash
rtk git add router/chatRouter.py
rtk git commit -m "feat: add session management routes to ChatRouter"
```

---

## Task 10: Smoke Test via API

- [ ] **Step 1: Start the server**

```bash
cd Chatbot_KPI_BE
uvicorn main:app --reload
```

- [ ] **Step 2: Send a chat message (creates a session automatically)**

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Berapa total KPI saya bulan ini?"}'
```

Expected: `200 OK` with `session_id` in response body. Copy that `session_id`.

- [ ] **Step 3: List sessions**

```bash
curl http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer <token>"
```

Expected: `200 OK` with array containing the session, title auto-set to first 80 chars of message.

- [ ] **Step 4: Rename the session**

```bash
curl -X PATCH http://localhost:8000/api/v1/chat/sessions/<session_id>/title \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "KPI Bulan Ini"}'
```

Expected: `200 OK` with updated `title` and `updated_at`.

- [ ] **Step 5: Delete the session**

```bash
curl -X DELETE http://localhost:8000/api/v1/chat/sessions/<session_id> \
  -H "Authorization: Bearer <token>"
```

Expected: `204 No Content`.

- [ ] **Step 6: Verify session is gone**

```bash
curl http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer <token>"
```

Expected: `200 OK` with empty array `[]`.

- [ ] **Step 7: Final commit**

```bash
rtk git add .
rtk git commit -m "feat: chat session management complete (list, delete, rename)"
```
