# Chat Session Service Split Design

## Goal

Split chat session lifecycle operations out of `service/chatService.py` so `ChatService` focuses on the ask/answer RAG pipeline and a new `ChatSessionService` owns session CRUD and ownership checks.

## Scope

Create `service/chatSessionService.py` for session-domain use cases:

- Create a session if it does not already exist.
- List sessions for a user.
- Delete a session after ownership validation.
- Update a session title after ownership validation.

Keep the existing API routes and response schemas unchanged.

## Service boundaries

`ChatService` remains responsible for:

- Processing chat questions.
- Clarification flow orchestration inside the pipeline.
- NL-to-SQL, SQL validation, SQL execution, optional chart generation, and result analysis.
- Audit history methods until a separate audit split is requested.

`ChatSessionService` becomes responsible for:

- Calling `ChatSessionRepository`.
- Creating the initial session for a chat request.
- Session ownership validation.
- Raising the current `HTTPException` responses for missing or forbidden sessions.

## Controller changes

`ChatController` session endpoints should instantiate `ChatSessionService` directly:

- `handle_get_sessions`
- `handle_delete_session`
- `handle_update_session_title`

Chat and clarification endpoints continue to instantiate `ChatService`.

## Data flow

For a normal chat request:

1. `ChatController.handle_chat()` calls `ChatService.process_query()`.
2. `ChatService.process_query()` creates or retrieves the session through `ChatSessionService.create_session_if_missing()`.
3. The RAG pipeline continues as before.

For session endpoints:

1. `ChatController` extracts the current user id.
2. `ChatController` delegates directly to `ChatSessionService`.
3. `ChatSessionService` performs repository calls and ownership checks.

## Verification

Run focused tests after implementation:

- `pytest tests/chat_schema_replacement_test.py -v`
- A Python import smoke test for `ChatService` and `ChatSessionService`

Run `pytest tests/chatbotManagement_test.py -v` only as a regression check; it currently has unrelated baseline failures.