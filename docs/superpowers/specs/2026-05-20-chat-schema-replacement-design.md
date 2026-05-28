# Chat Schema Replacement Design

## Goal

Replace the existing chat session, audit log, and clarification log storage with the schema described in `schema_dan_relasi.md`.

## Scope

The migration will drop these existing tables:

- `chatbot_audit_log`
- `chat_sessions`
- `clarification_logs`

It will create these replacement tables using repository-style snake_case names:

- `chat_sessions`
- `chat_messages`
- `clarification_questions`

Existing data in the dropped tables will not be preserved.

## Database schema

### `chat_sessions`

- `session_id` `VARCHAR(255)` primary key
- `session_name` `VARCHAR(255)`
- `start_at` timestamp
- `end_at` timestamp
- `user_id` foreign key to `users.id`
- `chatbot_id` foreign key to `chatbots.id`

### `chat_messages`

- `message_id` `VARCHAR(255)` primary key
- `message` `VARCHAR(255)`
- `is_sender_chatbot` boolean-compatible column for user/chatbot sender
- `send_at` timestamp
- `session_id` foreign key to `chat_sessions.session_id`

### `clarification_questions`

- `clarification_question_id` `VARCHAR(255)` primary key
- `ambiguous_phrase` `VARCHAR(255)`
- `ambiguity_type` `VARCHAR(20)`
- `clarification_question` `VARCHAR(255)`
- `answer_options` `VARCHAR(255)`
- `user_answer` integer
- `created_at` timestamp
- `message_id` foreign key to `chat_messages.message_id`

## ORM and code changes

Update the SQLAlchemy models to match the replacement schema:

- Update `ChatSession` to use `session_id`, `session_name`, `start_at`, `end_at`, `user_id`, and `chatbot_id`.
- Add `ChatMessage` with a relationship back to `ChatSession`.
- Add `ClarificationQuestion` with a relationship back to `ChatMessage`.
- Remove or stop importing old `ChatbotAuditLog` and `ClarificationLogORM` models so metadata matches the target schema.
- Adjust `User.sessions` and add any needed `Chatbot.sessions` relationship without changing unrelated chatbot behavior.

Repository and service changes should be limited to fixing imports or model field references that would otherwise break after the schema replacement.

## Migration strategy

Create a single Alembic revision after the current head that:

1. Drops indexes and tables for old clarification logs and chatbot audit logs if present.
2. Drops the old `chat_sessions` table.
3. Creates the replacement tables in dependency order: `chat_sessions`, `chat_messages`, then `clarification_questions`.
4. Adds indexes on foreign key columns used for lookups.

The downgrade can drop the new tables and recreate the previous tables with their known columns, or raise a clear downgrade limitation if preserving old data is not possible. The preferred implementation is reversible at the schema level.

## Verification

Run Alembic migration checks and relevant chatbot tests after implementation. At minimum, verify that the project imports all models successfully and the migration can create the new schema.