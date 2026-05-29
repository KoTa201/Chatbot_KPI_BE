# Chat Schema Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing chat session, chatbot audit log, and clarification log schema with the session/message/clarification-question schema from `schema_dan_relasi.md`.

**Architecture:** Use one Alembic migration to drop the old tables and create the new normalized chat tables. Update SQLAlchemy models and repositories so metadata and runtime imports match the new tables while keeping service behavior changes minimal.

**Tech Stack:** FastAPI, SQLAlchemy 2 async ORM, Alembic, PostgreSQL UUID/string columns, pytest.

---

## File structure

- Modify: `model/ChatSession.py` — define the new `chat_sessions` ORM schema and relationships.
- Create: `model/ChatMessage.py` — define messages belonging to chat sessions.
- Create: `model/ClarificationQuestion.py` — define clarification questions belonging to messages.
- Modify: `model/Chatbot.py` — add a `sessions` relationship to `ChatSession`.
- Modify: `model/User.py` — remove old audit log relationship and keep session relationship compatible with new schema.
- Modify: `model/__init__.py` — export new chat models and stop exporting dropped-table models.
- Modify: `repository/chatSessionRepository.py` — use `session_id`, `session_name`, and `start_at` fields.
- Modify: `repository/clarificationRepository.py` — replace old `clarification_logs` behavior with minimal `clarification_questions` persistence/query methods used by services.
- Modify: `repository/chatbotAuditLogRepository.py` — turn dropped audit-log repository into no-op read/write methods so chat pipeline keeps working without the removed table.
- Modify: `service/chatService.py` — remove audit deletion dependency during session deletion and fix string UUID comparison.
- Modify: `service/clarificationService.py` — adapt to new clarification repository return fields.
- Create: `alembic/versions/<new_revision>_replace_chat_schema.py` — drop old tables and create replacement tables.
- Test: `tests/chat_schema_replacement_test.py` — validate ORM metadata for the new schema.

---

### Task 1: Add ORM coverage test for replacement schema

**Files:**
- Create: `tests/chat_schema_replacement_test.py`

- [ ] **Step 1: Write the failing test**

Create `tests/chat_schema_replacement_test.py` with this content:

```python
from model.Base import Base
from model.ChatSession import ChatSession
from model.ChatMessage import ChatMessage
from model.ClarificationQuestion import ClarificationQuestion


def test_chat_schema_tables_are_registered():
    assert ChatSession.__tablename__ == "chat_sessions"
    assert ChatMessage.__tablename__ == "chat_messages"
    assert ClarificationQuestion.__tablename__ == "clarification_questions"

    assert "chatbot_audit_log" not in Base.metadata.tables
    assert "clarification_logs" not in Base.metadata.tables


def test_chat_sessions_columns_match_schema_doc():
    columns = set(ChatSession.__table__.columns.keys())

    assert columns == {
        "session_id",
        "session_name",
        "start_at",
        "end_at",
        "user_id",
        "chatbot_id",
    }
    assert ChatSession.__table__.primary_key.columns.keys() == ["session_id"]


def test_chat_messages_columns_match_schema_doc():
    columns = set(ChatMessage.__table__.columns.keys())

    assert columns == {
        "message_id",
        "message",
        "is_sender_chatbot",
        "send_at",
        "session_id",
    }
    assert ChatMessage.__table__.primary_key.columns.keys() == ["message_id"]


def test_clarification_questions_columns_match_schema_doc():
    columns = set(ClarificationQuestion.__table__.columns.keys())

    assert columns == {
        "clarification_question_id",
        "ambiguous_phrase",
        "ambiguity_type",
        "clarification_question",
        "answer_options",
        "user_answer",
        "created_at",
        "message_id",
    }
    assert ClarificationQuestion.__table__.primary_key.columns.keys() == [
        "clarification_question_id"
    ]
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
pytest tests/chat_schema_replacement_test.py -v
```

Expected: FAIL because `model.ChatMessage` and `model.ClarificationQuestion` do not exist yet, or because old tables are still registered.

- [ ] **Step 3: Commit is skipped for this task**

Do not commit yet. This repository already has unrelated working tree changes, so commit only if the user explicitly asks.

---

### Task 2: Replace ORM models

**Files:**
- Modify: `model/ChatSession.py`
- Create: `model/ChatMessage.py`
- Create: `model/ClarificationQuestion.py`
- Modify: `model/Chatbot.py`
- Modify: `model/User.py`
- Modify: `model/__init__.py`

- [ ] **Step 1: Replace `model/ChatSession.py`**

Replace the full file with:

```python
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage
    from model.Chatbot import Chatbot
    from model.User import User


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    chatbot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chatbots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="sessions", lazy="noload"
    )
    chatbot: Mapped["Chatbot"] = relationship(
        "Chatbot", back_populates="sessions", lazy="noload"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return (
            f"<ChatSession session_id={self.session_id} "
            f"session_name={self.session_name!r} user={self.user_id}>"
        )
```

- [ ] **Step 2: Create `model/ChatMessage.py`**

Create `model/ChatMessage.py` with:

```python
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatSession import ChatSession
    from model.ClarificationQuestion import ClarificationQuestion


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    is_sender_chatbot: Mapped[bool] = mapped_column(Boolean, nullable=False)
    send_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages", lazy="noload"
    )
    clarification_questions: Mapped[list["ClarificationQuestion"]] = relationship(
        "ClarificationQuestion",
        back_populates="message_ref",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:
        return f"<ChatMessage message_id={self.message_id} session={self.session_id}>"
```

- [ ] **Step 3: Create `model/ClarificationQuestion.py`**

Create `model/ClarificationQuestion.py` with:

```python
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from model.Base import Base

if TYPE_CHECKING:
    from model.ChatMessage import ChatMessage


class ClarificationQuestion(Base):
    __tablename__ = "clarification_questions"

    clarification_question_id: Mapped[str] = mapped_column(
        String(255), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    ambiguous_phrase: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ambiguity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    clarification_question: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_options: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_answer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    message_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("chat_messages.message_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    message_ref: Mapped["ChatMessage"] = relationship(
        "ChatMessage", back_populates="clarification_questions", lazy="noload"
    )

    @property
    def id(self) -> str:
        return self.clarification_question_id

    @property
    def clarifying_question(self) -> str:
        return self.clarification_question

    def __repr__(self) -> str:
        return (
            "<ClarificationQuestion "
            f"clarification_question_id={self.clarification_question_id}>"
        )
```

- [ ] **Step 4: Modify `model/Chatbot.py`**

Add `TYPE_CHECKING` and `relationship` imports, then add the relationship before `__repr__`.

The imports at the top should become:

```python
from typing import TYPE_CHECKING
from uuid import uuid4
from sqlalchemy import UUID, String, Text, Enum, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from model.Base import Base
from model.Base import AuthorityEnum

if TYPE_CHECKING:
    from model.ChatSession import ChatSession
```

Add this field inside `Chatbot` before `def __repr__`:

```python
    sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="chatbot", lazy="noload"
    )
```

- [ ] **Step 5: Modify `model/User.py`**

Remove the `ChatbotAuditLog` type-checking import and remove the `audit_logs` relationship block.

The `TYPE_CHECKING` block should be:

```python
if TYPE_CHECKING:
    from model.PasswordReset import PasswordReset
    from model.ChatSession import ChatSession
```

Delete this block:

```python
    audit_logs: Mapped[list["ChatbotAuditLog"]] = relationship(
        "ChatbotAuditLog", back_populates="user"
    )
```

- [ ] **Step 6: Modify `model/__init__.py`**

Replace the full file with:

```python
from .User import User
from .KPITracker import KPITracker
from .KPIGroup import KPIGroup
from .IngestionLog import IngestionLogORM
from .Chatbot import Chatbot
from .KPIMaster import KPIMaster
from .ChatSession import ChatSession
from .ChatMessage import ChatMessage
from .ClarificationQuestion import ClarificationQuestion
from .PasswordReset import PasswordReset
from .RevokedToken import RevokedToken
from .SchedulerConfig import SchedulerConfigModel
```

- [ ] **Step 7: Run schema metadata test**

Run:

```bash
pytest tests/chat_schema_replacement_test.py -v
```

Expected: PASS for ORM table registration tests, or FAIL only because repository/service imports still reference removed models.

---

### Task 3: Update repositories and services for new schema

**Files:**
- Modify: `repository/chatSessionRepository.py`
- Modify: `repository/clarificationRepository.py`
- Modify: `repository/chatbotAuditLogRepository.py`
- Modify: `service/chatService.py`
- Modify: `service/clarificationService.py`

- [ ] **Step 1: Replace `repository/chatSessionRepository.py`**

Replace the full file with:

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

    async def create(
        self,
        session_id: str,
        user_id: uuid.UUID,
        title: str,
        chatbot_id: uuid.UUID | None = None,
    ) -> ChatSession:
        session = ChatSession(
            session_id=session_id,
            user_id=user_id,
            chatbot_id=chatbot_id,
            session_name=title[:80].strip() or "New Chat",
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_user(self, user_id: uuid.UUID) -> list[ChatSession]:
        result = await self.db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.start_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, session_id: str) -> Optional[ChatSession]:
        result = await self.db.execute(
            select(ChatSession).where(ChatSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_title(self, session_id: str, title: str) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.session_name = title
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def end_session(self, session_id: str) -> Optional[ChatSession]:
        session = await self.get_by_id(session_id)
        if session is None:
            return None
        session.end_at = datetime.now(timezone.utc)
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

- [ ] **Step 2: Replace `repository/clarificationRepository.py`**

Replace the full file with:

```python
import json
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from model.ClarificationQuestion import ClarificationQuestion


class ClarificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        session_id: str,
        user_id: UUID,
        user_role: str,
        original_query: str,
        ambiguity_score: float,
        ambiguity_type: str,
        decision: str,
        decision_source: str,
        clarifying_question: str | None = None,
        clarification_answer: str | None = None,
        disambiguated_query: str | None = None,
        answer_options: list[str] | None = None,
        message_id: str | None = None,
    ) -> ClarificationQuestion:
        question = ClarificationQuestion(
            ambiguous_phrase=original_query[:255],
            ambiguity_type=ambiguity_type[:20] if ambiguity_type else None,
            clarification_question=clarifying_question or original_query[:255],
            answer_options=json.dumps(answer_options)[:255] if answer_options else None,
            user_answer=self._parse_user_answer(clarification_answer),
            message_id=message_id,
        )
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def update_with_answer(
        self,
        log_id: str,
        clarification_answer: str,
        disambiguated_query: str,
    ) -> ClarificationQuestion:
        stmt = select(ClarificationQuestion).where(
            ClarificationQuestion.clarification_question_id == str(log_id)
        )
        result = await self.db.execute(stmt)
        question = result.scalar_one_or_none()

        if not question:
            raise ValueError(f"Clarification question {log_id} tidak ditemukan")

        question.user_answer = self._parse_user_answer(clarification_answer)
        self.db.add(question)
        await self.db.flush()
        await self.db.refresh(question)
        return question

    async def get_last_clarification(self, session_id: str) -> ClarificationQuestion | None:
        stmt = (
            select(ClarificationQuestion)
            .order_by(desc(ClarificationQuestion.created_at))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_clarify_decisions_count(self, session_id: str) -> int:
        return 0

    async def delete_by_session(self, session_id: str) -> int:
        result = await self.db.execute(
            delete(ClarificationQuestion).where(ClarificationQuestion.message_id.is_(None))
        )
        await self.db.flush()
        return result.rowcount

    @staticmethod
    def _parse_user_answer(clarification_answer: str | None) -> int | None:
        if clarification_answer is None:
            return None
        try:
            return int(clarification_answer)
        except ValueError:
            return None
```

- [ ] **Step 3: Replace `repository/chatbotAuditLogRepository.py`**

Replace the full file with:

```python
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> dict:
        return data

    async def get_by_user(
        self,
        user_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Any]:
        return []

    async def get_by_session(self, session_id: str) -> list[Any]:
        return []

    async def get_failed_wireguard(
        self, skip: int = 0, limit: int = 100
    ) -> list[Any]:
        return []

    async def get_by_id(self, log_id: uuid.UUID) -> None:
        return None

    async def delete_by_session(self, session_id: str) -> int:
        return 0
```

- [ ] **Step 4: Modify `service/chatService.py` imports and deletion**

Keep `AuditLogRepository` import so existing history methods still return empty lists. In `delete_session`, change the user comparison and remove manual clarification/audit deletes.

Replace this block:

```python
        if str(session.user_id) != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.clarification_repo.delete_by_session(session_id)
        await self.audit_repo.delete_by_session(session_id)
        await self.session_repo.delete(session_id)
```

with:

```python
        if str(session.user_id) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Anda tidak memiliki akses ke session ini.",
            )
        await self.session_repo.delete(session_id)
```

Also replace the same comparison in `update_session_title`:

```python
        if str(session.user_id) != str(user_id):
```

- [ ] **Step 5: Modify `service/clarificationService.py` field usage**

Replace:

```python
        logger.info(f"[ClarificationService] Clarification logged: {log.id}")
```

with:

```python
        logger.info(
            "[ClarificationService] Clarification logged: "
            f"{log.clarification_question_id}"
        )
```

Replace:

```python
        original_query = last_log.original_query
        clarifying_question = last_log.clarifying_question
```

with:

```python
        original_query = last_log.ambiguous_phrase or ""
        clarifying_question = last_log.clarification_question
```

Replace:

```python
            log_id=last_log.id,
```

with:

```python
            log_id=last_log.clarification_question_id,
```

Replace:

```python
            f"[ClarificationService] Clarification response recorded: {last_log.id}"
```

with:

```python
            "[ClarificationService] Clarification response recorded: "
            f"{last_log.clarification_question_id}"
```

- [ ] **Step 6: Run import and schema tests**

Run:

```bash
pytest tests/chat_schema_replacement_test.py -v
```

Expected: PASS.

---

### Task 4: Add Alembic migration for replacement schema

**Files:**
- Create: `alembic/versions/<new_revision>_replace_chat_schema.py`

- [ ] **Step 1: Check current Alembic head**

Run:

```bash
alembic heads
```

Expected: one current head revision. Use that value as `down_revision` in the new migration. If there are multiple heads, stop and merge heads first instead of guessing.

- [ ] **Step 2: Create the migration file**

Run:

```bash
alembic revision -m "replace chat schema"
```

Expected: a new file appears under `alembic/versions/`.

- [ ] **Step 3: Replace the generated migration content**

Use the generated revision ID and down revision from the generated file. Replace the upgrade/downgrade bodies with this structure:

```python
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "<generated_revision>"
down_revision: Union[str, None] = "<current_head>"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clarification_logs_user_id")
    op.execute("DROP INDEX IF EXISTS ix_clarification_logs_session_id")
    op.execute("DROP INDEX IF EXISTS ix_chatbot_audit_log_user_id")
    op.execute("DROP INDEX IF EXISTS ix_chatbot_audit_log_session_id")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_user_id")
    op.drop_table("clarification_logs", if_exists=True)
    op.drop_table("chatbot_audit_log", if_exists=True)
    op.drop_table("chat_sessions", if_exists=True)

    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("session_name", sa.String(length=255), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("chatbot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chatbot_id"], ["chatbots.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_chatbot_id", "chat_sessions", ["chatbot_id"])

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("is_sender_chatbot", sa.Boolean(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])

    op.create_table(
        "clarification_questions",
        sa.Column("clarification_question_id", sa.String(length=255), nullable=False),
        sa.Column("ambiguous_phrase", sa.String(length=255), nullable=True),
        sa.Column("ambiguity_type", sa.String(length=20), nullable=True),
        sa.Column("clarification_question", sa.String(length=255), nullable=False),
        sa.Column("answer_options", sa.String(length=255), nullable=True),
        sa.Column("user_answer", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.message_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("clarification_question_id"),
    )
    op.create_index(
        "ix_clarification_questions_message_id",
        "clarification_questions",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_clarification_questions_message_id", table_name="clarification_questions")
    op.drop_table("clarification_questions")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_chatbot_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])

    op.create_table(
        "chatbot_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_role", sa.String(length=20), nullable=True),
        sa.Column("user_query", sa.Text(), nullable=True),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("wireguard_status", sa.String(length=10), nullable=True),
        sa.Column("wireguard_reason", sa.Text(), nullable=True),
        sa.Column("execution_status", sa.String(length=20), nullable=True),
        sa.Column("rows_returned", sa.Integer(), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chatbot_audit_log_session_id", "chatbot_audit_log", ["session_id"])
    op.create_index("ix_chatbot_audit_log_user_id", "chatbot_audit_log", ["user_id"])

    op.create_table(
        "clarification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_role", sa.String(length=50), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("ambiguity_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("ambiguity_type", sa.String(length=50), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("decision_source", sa.String(length=20), nullable=False),
        sa.Column("clarifying_question", sa.Text(), nullable=True),
        sa.Column("clarification_answer", sa.Text(), nullable=True),
        sa.Column("disambiguated_query", sa.Text(), nullable=True),
        sa.Column("user_feedback", sa.Boolean(), nullable=True),
        sa.Column("needed_correction", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_clarification_logs_session_id", "clarification_logs", ["session_id"])
    op.create_index("ix_clarification_logs_user_id", "clarification_logs", ["user_id"])
```

- [ ] **Step 4: Run migration syntax check**

Run:

```bash
python -m py_compile alembic/versions/<new_revision>_replace_chat_schema.py
```

Expected: no output and exit code 0.

---

### Task 5: Verify integration surface

**Files:**
- Test: `tests/chat_schema_replacement_test.py`
- Test: existing chatbot tests if available

- [ ] **Step 1: Run schema replacement test**

Run:

```bash
pytest tests/chat_schema_replacement_test.py -v
```

Expected: all tests PASS.

- [ ] **Step 2: Run chatbot management tests**

Run:

```bash
pytest tests/chatbotManagement_test.py -v
```

Expected: tests PASS, or fail only for pre-existing fixture/data assumptions unrelated to chat schema. If failures mention removed models or `ChatSession` fields, fix those references before continuing.

- [ ] **Step 3: Run import smoke test**

Run:

```bash
python - <<'PY'
import model
from model.Base import Base
print(sorted(name for name in Base.metadata.tables if name in {
    'chat_sessions',
    'chat_messages',
    'clarification_questions',
    'chatbot_audit_log',
    'clarification_logs',
}))
PY
```

Expected output:

```text
['chat_messages', 'chat_sessions', 'clarification_questions']
```

- [ ] **Step 4: Check working tree**

Run:

```bash
git status --short
```

Expected: new/modified files from this plan plus pre-existing user changes. Do not stage or commit unless the user explicitly asks.

---

## Self-review

Spec coverage:

- Drops `chatbot_audit_log`, old `chat_sessions`, and `clarification_logs`: Task 4.
- Creates `chat_sessions`, `chat_messages`, and `clarification_questions`: Tasks 2 and 4.
- Updates ORM models and relationships: Task 2.
- Keeps service changes minimal while avoiding broken imports: Task 3.
- Verifies model imports and schema shape: Tasks 1 and 5.

Placeholder scan: no placeholders remain except `<generated_revision>` and `<current_head>`, which are explicitly produced by the Alembic command in Task 4 and must be substituted with generated values.

Type consistency: repository/service code uses `session_id`, `session_name`, `start_at`, `clarification_question_id`, and `clarification_question`, matching the ORM definitions above.
