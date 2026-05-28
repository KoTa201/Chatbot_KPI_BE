# Chatbot English Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename chatbot attributes from Indonesian to English across the API, ORM, database table, and tests.

**Architecture:** Use a direct breaking rename: `nama_chatbot` becomes `chatbot_name`, and `otoritas` becomes `authority`. Preserve existing data through Alembic column/index renames rather than drop/add operations.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy async ORM, Alembic, pytest.

---

### Task 1: Update tests to expect English chatbot fields

**Files:**
- Modify: `tests/chatbotManagement_test.py`

- [ ] **Step 1: Replace test payload helper and assertions**

Use project-wide replacement in `tests/chatbotManagement_test.py`:

```python
# Replace identifier and JSON key usage:
nama_chatbot -> chatbot_name
otoritas -> authority

# Replace helper parameter names:
def make_payload(
    name: str = "HR Assistant",
    authority: str = "kepala_divisi",
    addon_prompt: str | None = "Kamu adalah asisten kepala_divisi yang ramah.",
) -> dict:
    return {"chatbot_name": name, "authority": authority, "addon_prompt": addon_prompt}
```

- [ ] **Step 2: Update helper call keyword arguments**

Replace calls like:

```python
make_payload(nama="Karyawan Bot", otoritas="karyawan")
seed_chatbot(db_session, nama_chatbot="Bot A", otoritas=AuthorityEnum.KARYAWAN)
```

with:

```python
make_payload(name="Karyawan Bot", authority="karyawan")
seed_chatbot(db_session, chatbot_name="Bot A", authority=AuthorityEnum.KARYAWAN)
```

- [ ] **Step 3: Run focused tests to verify failure before implementation**

Run: `pytest tests/chatbotManagement_test.py -q`
Expected before implementation: failures mentioning missing `chatbot_name`/`authority` fields or `Chatbot` constructor invalid keyword arguments.

### Task 2: Rename model and schemas

**Files:**
- Modify: `model/Chatbot.py`
- Modify: `schema/chatbotSchema.py`

- [ ] **Step 1: Update ORM mapped attributes**

In `model/Chatbot.py`, change the class fields to:

```python
chatbot_name: Mapped[str] = mapped_column(
    String(255), nullable=False, index=True)
authority: Mapped[AuthorityEnum] = mapped_column(
    Enum(AuthorityEnum, values_callable=lambda e: [x.value for x in e]),
    nullable=False)
```

Update `__repr__` to:

```python
return f"<Chatbot id={self.id} name='{self.chatbot_name}' authority='{self.authority}'>"
```

- [ ] **Step 2: Update Pydantic request/response fields**

In `schema/chatbotSchema.py`, replace `nama_chatbot` with `chatbot_name`, replace `otoritas` with `authority`, and rename validators to target `chatbot_name`:

```python
@field_validator("chatbot_name")
@classmethod
def strip_chatbot_name(cls, v: str) -> str:
    return v.strip()
```

For `ChatbotUpdate`, use:

```python
@field_validator("chatbot_name")
@classmethod
def strip_chatbot_name(cls, v: Optional[str]) -> Optional[str]:
    return v.strip() if v else v
```

### Task 3: Update repository and service references

**Files:**
- Modify: `repository/chatbotRepository.py`
- Modify: `service/chatbotService.py`

- [ ] **Step 1: Update repository method names and ORM field access**

In `repository/chatbotRepository.py`, rename `get_by_nama(self, nama_chatbot: str)` to:

```python
async def get_by_chatbot_name(self, chatbot_name: str) -> Optional[Chatbot]:
    result = await self.db.execute(
        select(Chatbot).where(
            (func.lower(Chatbot.chatbot_name) == chatbot_name.lower()) &
            (Chatbot.is_active == True)
        )
    )
    return result.scalars().first()
```

Update filtering/searching to use `Chatbot.authority` and `Chatbot.chatbot_name`.

- [ ] **Step 2: Update service uniqueness and active-authority logic**

In `service/chatbotService.py`, rename helper `_check_nama_unique` to `_check_chatbot_name_unique`, call `self.repo.get_by_chatbot_name(chatbot_name)`, and update all payload references:

```python
await self._check_chatbot_name_unique(payload.chatbot_name)
await self._enforce_single_active_per_authority(payload.authority)
```

In update logic, use:

```python
if payload.chatbot_name:
    await self._check_chatbot_name_unique(payload.chatbot_name, exclude_id=chatbot_id)

target_authority = payload.authority if payload.authority is not None else existing.authority
```

### Task 4: Add Alembic migration

**Files:**
- Create: `alembic/versions/<new_revision>_rename_chatbot_attributes_to_english.py`

- [ ] **Step 1: Generate migration revision**

Run: `alembic revision -m "rename chatbot attributes to english"`
Expected: a new file in `alembic/versions/`.

- [ ] **Step 2: Implement upgrade and downgrade**

Set `down_revision` to the current head revision. Implement:

```python
def upgrade() -> None:
    op.drop_index(op.f('ix_chatbots_nama_chatbot'), table_name='chatbots')
    op.alter_column('chatbots', 'nama_chatbot', new_column_name='chatbot_name')
    op.alter_column('chatbots', 'otoritas', new_column_name='authority')
    op.create_index(op.f('ix_chatbots_chatbot_name'), 'chatbots', ['chatbot_name'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chatbots_chatbot_name'), table_name='chatbots')
    op.alter_column('chatbots', 'authority', new_column_name='otoritas')
    op.alter_column('chatbots', 'chatbot_name', new_column_name='nama_chatbot')
    op.create_index(op.f('ix_chatbots_nama_chatbot'), 'chatbots', ['nama_chatbot'], unique=False)
```

### Task 5: Update remaining references and verify

**Files:**
- Search all Python files for old names.

- [ ] **Step 1: Search for old attributes**

Run equivalent searches for:

```text
nama_chatbot
otoritas
get_by_nama
_check_nama_unique
```

Expected: no remaining code references for chatbot attribute/API names, except unrelated Indonesian text if intentionally left in messages or comments.

- [ ] **Step 2: Run focused test suite**

Run: `pytest tests/chatbotManagement_test.py -q`
Expected: all tests pass.

- [ ] **Step 3: Run migration sanity check if database environment is configured**

Run: `alembic upgrade head`
Expected: migration applies successfully. If `DATABASE_URL` is not configured, report that migration execution could not be verified locally.
