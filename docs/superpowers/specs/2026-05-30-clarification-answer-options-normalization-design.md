# Clarification Answer Options Normalization Design

## Goal

Normalize `clarification_questions.answer_options` to satisfy first normal form. Existing option data in the old column will be dropped during migration. Public API response shape stays unchanged: clarification questions still expose `options: list[str]`.

## Chosen Approach

Use a child table with ordered option rows.

Create `clarification_question_answer_options` with:

- primary key id
- `clarification_question_id` foreign key to `clarification_questions.clarification_question_id`
- `option_text` text value
- `option_order` integer display order

`ClarificationQuestion` owns many answer options. Deleting a clarification question cascades to its option rows. Option rows are always read ordered by `option_order`.

## Schema and Migration

Add a SQLAlchemy model for clarification answer options and add a relationship to `ClarificationQuestion`.

Alembic migration will:

1. Create `clarification_question_answer_options`.
2. Drop `clarification_questions.answer_options`.
3. On downgrade, recreate `clarification_questions.answer_options` as nullable text and drop the child table.

No migration step copies existing option strings. Old values are intentionally discarded.

## Code Interaction

`ClarificationRepository.create()` will stop serializing option lists into JSON. It will create the `ClarificationQuestion`, flush to obtain its id, then insert one child row per option with a stable `option_order`.

Read paths that need options will eager-load the relationship:

- clarification repository session/history reads
- chat message repository session detail reads

Response mapping will derive options from related rows:

```python
options = [option.option_text for option in question.answer_options]
```

`selected_answer` and `free_text_answer` behavior stays unchanged.

## API Compatibility

External response schemas do not change. Clients still send and receive option lists through existing Pydantic schemas.

Only persistence changes:

- old: one text column containing serialized list
- new: one row per option in child table

## Error Handling

Creating a clarification without options creates no child rows. Session/detail responses return an empty list when no option rows exist.

Database-level FK cascade handles cleanup when a clarification question is deleted.

## Testing

Update focused tests to verify:

- `ClarificationQuestion` no longer has `answer_options` column.
- new answer option model/table exists with FK and `option_order`.
- repository creation persists options as child rows in original order.
- session detail response returns `options` from relationship rows.
- API response shape remains unchanged.

No test preserves old serialized option data, because migration drops it by requirement.
