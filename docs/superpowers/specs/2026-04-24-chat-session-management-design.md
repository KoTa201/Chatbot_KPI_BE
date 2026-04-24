# Chat Session Management — Design Spec

**Date:** 2026-04-24
**Status:** Approved

## Overview

Add backend support for chat session management: list sessions, delete a session (hard delete), and rename a session title. Sessions are scoped strictly to the user who created them.

---

## 1. Database

### New Table: `chat_sessions`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | PK, default uuid4 |
| `user_id` | UUID | FK → `users.id` ON DELETE SET NULL, indexed |
| `title` | String(255) | NOT NULL |
| `created_at` | DateTime | server default NOW() |
| `updated_at` | DateTime | server default NOW(), updated at application level on rename |

### Changes to Existing Tables

- `chatbot_audit_log.session_id` — add FK → `chat_sessions.id` ON DELETE CASCADE
- `clarification_logs.session_id` — add FK → `chat_sessions.id` ON DELETE CASCADE

Cascade ensures hard-deleting a session row automatically removes all its audit log and clarification log rows atomically.

### Migration

File: `alembic/versions/014_create_chat_sessions.py`

Steps:
1. Create `chat_sessions` table
2. Alter `chatbot_audit_log` — add FK constraint on `session_id`
3. Alter `clarification_logs` — add FK constraint on `session_id`

---

## 2. API Endpoints

All endpoints require a valid JWT (`get_current_user`). Session data is always scoped to `current_user.id`.

| Method | Path | Description | Status Codes |
|---|---|---|---|
| `GET` | `/api/v1/chat/sessions` | List all sessions for the logged-in user | 200 |
| `DELETE` | `/api/v1/chat/sessions/{session_id}` | Hard-delete session + cascade all messages | 204, 403, 404 |
| `PATCH` | `/api/v1/chat/sessions/{session_id}/title` | Rename session title | 200, 403, 404 |

### Schemas

```python
# GET /sessions response item
class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

# PATCH /sessions/{id}/title request
class UpdateSessionTitleRequest(BaseModel):
    title: str  # validated: non-empty, max 255 chars
```

### Session Auto-Creation

When `POST /api/v1/chat` is called:
- If `request.session_id` is None, create a new `chat_sessions` row and generate a new UUID.
- If `request.session_id` is provided and already exists in `chat_sessions`, skip creation and use the existing session.
- Title is auto-set to the first 80 characters of `request.message` (stripped).
- The generated `session_id` (UUID) is returned in `ChatResponse.session_id`.

### Ownership Enforcement

On `DELETE` and `PATCH`, the service fetches the session by `session_id` and checks `session.user_id == current_user.id`.
- Returns `404` if session not found.
- Returns `403` if session belongs to another user.

---

## 3. Layer Breakdown

### Model: `model/ChatSession.py`

SQLAlchemy ORM class for `chat_sessions`. Relationships:
- `user` → `UserORM` (back_populates)
- `audit_logs` → `ChatbotAuditLog` (back_populates)
- `clarification_logs` → `ClarificationLog` (back_populates)

### Repository: `repository/chatSessionRepository.py`

| Method | Description |
|---|---|
| `create(session_id, user_id, title)` | Insert new session row |
| `get_by_user(user_id)` | Return all sessions for a user, ordered by `created_at` desc |
| `get_by_id(session_id)` | Fetch single session or None |
| `update_title(session_id, title)` | Update title and `updated_at` |
| `delete(session_id)` | Delete session row; cascade handles child rows |

### Service: `service/chatService.py` (additions)

| Method | Description |
|---|---|
| `create_session(session_id, user_id, title)` | Called at start of `process_query()` for new sessions |
| `get_sessions(user_id)` | Returns list of sessions for user |
| `delete_session(session_id, user_id)` | Ownership check → delete |
| `update_session_title(session_id, user_id, title)` | Ownership check → update title |

### Controller: `controller/chatController.py` (additions)

| Handler | Description |
|---|---|
| `handle_get_sessions(current_user)` | Calls `get_sessions`, returns `list[SessionResponse]` |
| `handle_delete_session(session_id, current_user)` | Calls `delete_session`, returns 204 |
| `handle_update_session_title(session_id, title, current_user)` | Calls `update_session_title`, returns `SessionResponse` |

### Router: `router/chatRouter.py` (additions)

Three new routes registered in `setup_routes()`:
- `GET /sessions` → `get_sessions` handler
- `DELETE /sessions/{session_id}` → `delete_session` handler
- `PATCH /sessions/{session_id}/title` → `update_session_title` handler

---

## 4. Error Handling

| Scenario | HTTP Status |
|---|---|
| Session not found | 404 |
| Session belongs to another user | 403 |
| Title is empty or > 255 chars | 422 (Pydantic validation) |
| `process_query()` called with existing valid session_id | No new session created |

---

## 5. Out of Scope

- Soft delete (sessions are hard-deleted with cascade)
- Admin access to other users' sessions (owner-only)
- Session search or filtering beyond listing all user sessions
- Pagination for session list (can be added later if needed)
