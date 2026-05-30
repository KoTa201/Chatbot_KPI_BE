# Service Refactor Design

Date: 2026-05-30

## Goal

Refactor these service files for clean code, lower code smells, and maintainability:

- `service/chatService.py`
- `service/clarificationService.py`
- `service/ambiguityDetectorService.py`
- `service/graphicService.py`

Behavior must stay compatible with existing endpoints, schemas, repository contracts, prompt builders, and tests. New helper modules may be added when they create clearer boundaries.

## Chosen Approach

Use a pipeline-object plus helper-module approach.

This approach keeps the four tagged services as public entry points while moving repeated formatting, parsing, and state mutation into small testable units. It avoids a full rewrite, keeps risk moderate, and still addresses long methods, magic strings, duplicate code, deep nesting, and large-class pressure.

## Non-Goals

- No endpoint contract changes.
- No schema response shape changes.
- No repository API changes.
- No prompt-builder redesign.
- No broad architectural rewrite beyond helper extraction needed by the four tagged services.
- No change to clarification separation: ambiguity detection stays separate from clarification-question formatting/generation.

## Architecture

### `chatService.py`

`ChatService` remains the chat pipeline orchestrator. It should mostly coordinate stages and persistence, not build ad-hoc payloads or mutate untyped dictionary state everywhere.

Planned boundaries:

- Keep `process_query()` as entry point.
- Extract stage state into a typed context object.
- Extract response/payload formatting into a response builder helper.
- Keep SQL validation and execution calls inside chat pipeline.
- Replace debug-like root logging with module logger.
- Remove comments that repeat code behavior.

### `clarificationService.py`

`ClarificationService` remains clarification orchestrator. It should coordinate detection, question persistence, answer handling, preference-tree updates, re-checks, and commits.

Planned boundaries:

- Extract answer normalization and QA-pair building.
- Extract merge logic for current answers plus session history.
- Extract repeated-question filtering.
- Extract fallback disambiguated-query builder.
- Keep question formatting/generation outside `AmbiguityDetectorService`.

### `ambiguityDetectorService.py`

`AmbiguityDetectorService` remains an LLM-only detector.

Planned boundaries:

- Extract JSON parsing into helper module.
- Extract AmbiSQL `question_set` normalization.
- Extract legacy ambiguity-result normalization.
- Extract fallback non-ambiguous result creation.
- Keep detector flow short: build prompt, call LLM, normalize response.

### `graphicService.py`

`GraphicSeervice` public API remains compatible:

- `generateGraphic()`
- `generateGraphicPerKpi()`

Planned boundaries:

- Keep parser behavior compatible.
- Move or group chart constants, hints, thresholds, and colors.
- Reduce large method pressure through focused helpers where behavior is touched.
- Remove comments that describe what code already says.
- Keep one-KPI render failure from stopping other KPI charts.

The typo `GraphicSeervice` is not renamed in this refactor because that would require caller-wide updates and raises risk without improving behavior for current goal.

## Proposed Helper Modules

### `service/chatPipelineTypes.py`

Typed pipeline context dataclass with fields for:

- `session_id`
- `user_id`
- `user_role`
- `user_query`
- `generated_sql`
- `wireguard_status`
- `wireguard_reason`
- `execution_status`
- `rows_returned`
- `execution_time_ms`

Purpose: replace repeated magic dictionary keys with typed state.

### `service/chatResponseBuilder.py`

Functions for:

- clarification prompt message formatting
- graphic payload building
- blocked security response message
- AI-unavailable response message

Purpose: keep `ChatService` focused on orchestration.

### `service/clarificationHelpers.py`

Functions for:

- effective answer selection (`Lainnya` with free text)
- submitted QA-pair construction
- session QA-pair merge with current answers overriding history
- answered question key generation
- repeated ambiguity filtering
- fallback disambiguated query construction

Purpose: make clarification logic easier to unit test without database.

### `service/ambiguityParsing.py`

Functions for:

- parse fenced or wrapped JSON object from LLM response
- normalize AmbiSQL `question_set`
- normalize legacy ambiguity payload
- build non-ambiguous fallback result
- map LLM-sourced versus database-sourced level-1 labels

Purpose: keep detector service small and parser behavior covered by focused tests.

### `service/graphicConstants.py` (optional)

Constants for:

- supported chart types
- value/target/category/month hints
- month labels
- color thresholds
- KPI parser header words and scale map if extraction stays readable

Purpose: reduce magic strings and make chart behavior easier to inspect.

## Data Flow

Chat pipeline remains:

1. Load active chatbot for user role and addon prompt.
2. Create session if missing.
3. Persist user message only when query is not coming from clarification context.
4. Run ambiguity detection and clarification handling.
5. Return early if clarification questions are needed.
6. Generate SQL through LLM.
7. Decide whether visualization is requested.
8. Validate generated SQL through guardrails.
9. Execute sanitized SQL with timeout.
10. Generate graphics only when requested.
11. Analyze results through LLM.
12. Persist chatbot message and commit.
13. Return `ChatResponse` with same fields as before.

## Error Handling

Public behavior stays the same:

- NL-to-SQL LLM unavailable returns user-safe AI-unavailable response.
- Guardrail rejection returns security-blocked message.
- SQL timeout raises `408`.
- SQL execution failure raises `422`.
- Analysis `429` returns degraded narrative.
- Unexpected server errors roll back and return user-safe server error.

Refactor should reduce nested error blocks where possible, but not change semantics.

## Testing Plan

Use focused tests, plus relevant existing regression tests.

Add or update tests for:

- ambiguity parser handles fenced JSON and AmbiSQL `question_set`.
- ambiguity parser returns fallback non-ambiguous result on LLM failure path.
- clarification helpers build QA pairs from submitted answers.
- clarification helpers merge session history with current answers, with current answers winning.
- clarification helpers filter already-answered repeated questions.
- chat response builder returns same clarification and blocked-response message shape.
- graphic extraction smoke tests only if helper extraction changes import or behavior boundaries.

Run:

```bash
pytest tests/clarificationMechanism_test.py -v
pytest tests/chatPipeline_test.py -v
```

Run graphic-related tests too if repository has focused graphic tests.

## Risks and Mitigations

- Risk: helper extraction changes subtle message strings. Mitigation: snapshot expected strings in focused tests where practical, and avoid changing user-facing messages unless necessary.
- Risk: typed context changes dictionary access behavior. Mitigation: keep equivalent field names and update all writes in one pass.
- Risk: graphic rendering is sensitive to pandas/matplotlib behavior. Mitigation: keep public methods and chart selection logic compatible; avoid broad renderer rewrite.
- Risk: ambiguity parsing handles multiple LLM output formats. Mitigation: isolate parsing and add tests for both AmbiSQL `question_set` and legacy payload.

## Completion Criteria

- Tagged services read cleaner and have shorter focused helpers.
- No behavior change to public API.
- Ambiguity detection remains separate from clarification-question formatting.
- Magic strings and repeated payload-building are reduced.
- Focused tests pass.
- Relevant existing chat/clarification tests pass.
