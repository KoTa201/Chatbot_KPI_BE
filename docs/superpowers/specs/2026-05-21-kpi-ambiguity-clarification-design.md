# KPI Ambiguity Clarification Design

## Context

The current clarification mechanism is LLM-only, detects a single broad ambiguity type, asks at most one clarification question per query, and uses generic types such as `scope`, `metric`, `temporal`, `aggregation`, and `referential`. The PRD requires an AmbiSQL-style flow for KPI Text-to-SQL: detect multiple ambiguous phrases, classify them with a structured taxonomy, ask batched multiple-choice clarification questions, rewrite the query from the answers, and continue into the existing RAG pipeline.

This design implements the multi-question backend foundation while keeping the scope focused on the existing FastAPI chatbot backend. Preference management UI, SQL before/after diff UI, and full user-facing preference settings are deferred.

## Goals

- Detect multiple ambiguities in one KPI natural-language query.
- Classify ambiguities with PRD-aligned AmbiSQL taxonomy.
- Ground detection and answer options in KPI schema/sample context.
- Return all clarification questions as one batch.
- Accept a list of clarification answers and rewrite the query once.
- Preserve the existing direct NL-to-SQL path for clear queries.
- Keep graceful fallback behavior if LLM-based ambiguity handling fails.

## Non-goals

- Building frontend UI for the clarification panel.
- Implementing user preference management screens.
- Implementing SQL before/after visual diff.
- Adding automatic resolution without user confirmation.
- Supporting additional data sources beyond the current KPI backend data.

## Architecture

### Ambiguity detection

`AmbiguityDetectorService` will return a multi-ambiguity result instead of a single score/type result. Each detected item will include:

- `ambiguous_phrase`
- `ambiguity_type`
- `ambiguity_score`
- `possible_interpretations`
- `suggested_clarifying_question`
- `answer_options`
- optional grounding metadata such as candidate columns or sample values

The detector remains LLM-based, but its prompt will receive concise KPI schema/sample context before analysis. The prompt taxonomy will use:

- `AmbiSchema`
- `AmbiValue`
- `AmbiIntent`
- `AmbiContext`
- `AmbiFallacy`
- `AmbiRef`

`AmbiSource` is intentionally omitted for this implementation because the current backend is focused on one KPI data domain and does not expose multiple user-selectable data sources.

### KPI context builder

A small service/helper will build a compact context payload for ambiguity detection and clarification generation. It should describe current KPI domain concepts in business language:

- KPI Master definitions and target/activity fields
- KPI Tracker realization records
- periods: month, year, and date-like references
- organizational dimensions: user, employee, division, or department fields available in the current schema
- metric concepts: target, realization, achievement percentage, status
- representative sample values where safe and available

This context is not a full database dump. It should be bounded and suitable for prompt use.

### Clarification question generation

`ClarificationQuestionGeneratorService` will generate or normalize one question per detected ambiguity. The service will ensure each question has:

- one specific business-language question
- 2 to 5 relevant options from the LLM/schema context
- a default `Lewati` option
- a default `Lainnya` option
- optional metadata describing which schema/sample candidates informed the options

Questions should avoid SQL terminology in user-facing text.

### Clarification orchestration

`ClarificationService` will:

1. Build KPI schema/sample context.
2. Detect all ambiguities.
3. Prioritize detected ambiguities by confidence and KPI impact.
4. Limit the returned batch to a practical maximum of 3 questions.
5. Generate/normalize each clarification question.
6. Store each question as a separate row tied to the relevant session/message where possible.
7. Return one batched clarification response.

If no ambiguity is found, it returns `None` and the existing pipeline continues.

### Query rewriting

`/chat/clarification` will accept answers for all returned questions. The rewriting prompt will combine:

- original query
- all clarification questions
- each selected option or free-text answer
- skipped items marked by `Lewati`
- optional additional constraints

The rewriter will produce one precise KPI natural-language query. That rewritten query then re-enters the existing chat pipeline with ambiguity detection skipped for that immediate pipeline run.

## API and schema changes

### Chat response

`ChatResponse` should add a batched field such as:

```python
clarification_questions: list[ClarificationQuestionResponse] | None = None
```

Each `ClarificationQuestionResponse` should include:

```python
id: str
ambiguous_phrase: str | None
ambiguity_type: str
question: str
options: list[str]
metadata: dict | None
```

The existing single-question fields can be removed or left temporarily only if tests or current clients still need them during the same backend change. The preferred backend shape is the batched field.

### Chat clarification request

`ChatRequest` or a dedicated clarification request schema should support:

```python
session_id: UUID
clarification_answers: list[ClarificationAnswer]
additional_constraints: str | None = None
show_sql: bool = False
```

Each answer should include:

```python
question_id: str
selected_option: str
free_text: str | None = None
```

When `selected_option` is `Lainnya`, `free_text` is authoritative. When `selected_option` is `Lewati`, the ambiguity is intentionally unresolved and should be recorded as skipped.

## Storage

The current `ClarificationRepository` must become session-aware. `get_last_clarification` and `get_by_session` must filter by the current session or by questions linked to messages in that session, rather than returning global latest questions.

`ClarificationQuestion` storage should preserve answer text/free text. The current integer-only `user_answer` parsing is insufficient for options such as `Fiscal Year 2024`, `IT & Digital`, `Lewati`, or arbitrary `Lainnya` text. The model/migration should add fields or adapt storage so selected answer text and free-text answer are not lost.

Each question row should store enough audit data to reconstruct:

- original query or ambiguous phrase
- ambiguity type
- generated question
- answer options
- selected answer
- free-text answer if provided
- created timestamp
- session/message association

## KPI-domain behavior

The prompt and fallback templates should be tuned to this project’s KPI language:

- AmbiSchema: ambiguous KPI metrics such as “terbaik”, “performa”, “achievement”, “nilai”, “target”, and “realisasi”.
- AmbiValue: fuzzy or informal references to divisions, KPI names/categories, employee/user names, periods, and statuses.
- AmbiIntent: unclear request intent such as ranking, filtering, grouping, listing, comparing, or aggregating.
- AmbiContext: missing business context such as currency, active/inactive scope, or organizational boundary.
- AmbiFallacy: assumptions that may conflict with available data.
- AmbiRef: vague temporal/spatial references such as “bulan ini”, “tahun lalu”, “Q3”, “awal tahun”, or “setelah target tercapai”.

For AmbiRef, generated options should prefer concrete periods or date ranges when possible.

## Limits and fallback behavior

- Return at most 3 clarification questions per batch.
- Treat borderline/low-confidence ambiguity as direct answer to avoid excessive friction.
- If detection, question generation, storage, or rewriting fails because of LLM/provider issues, continue with the existing direct NL-to-SQL path when safe.
- If a malformed clarification response references unknown question IDs, return a 400/404 error rather than rewriting from unmatched answers.
- If all answers are `Lewati`, proceed with the original query and include skipped assumptions in the rewrite/log context.

## Testing plan

Update and add tests for:

- multi-item ambiguity detector JSON output
- PRD taxonomy handling
- fenced JSON parsing
- invalid JSON/LLM failure fallback
- no-ambiguity direct path
- option normalization with `Lewati` and `Lainnya`
- batched clarification response from `ClarificationService`
- session-scoped question lookup
- list-of-answers query rewriting
- `Lewati` answer behavior
- `Lainnya` plus `free_text` behavior
- additional constraints included in rewrite prompt
- chat pipeline stopping at batched clarification and continuing after answers

Existing tests for clear KPI queries bypassing clarification should remain.

## Implementation sequence

1. Update schemas for multi-ambiguity detection, batched questions, and batched answers.
2. Add KPI context builder for prompt grounding.
3. Update ambiguity prompts to use PRD taxonomy and return arrays.
4. Update detector parsing/fallback logic.
5. Update question generator normalization and fallback templates.
6. Update model/migration/repository storage for session-aware batched questions and text answers.
7. Update clarification orchestration and rewriting.
8. Update chat controller/service request and response handling.
9. Update tests for detector, generator, service, repository behavior, and chat pipeline integration.
