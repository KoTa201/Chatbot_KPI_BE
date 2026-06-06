# Scope and Addon Policy Precheck Design

## Context

`build_ambiguity_assessment_prompt` currently handles both out-of-scope detection and ambiguity detection. The desired behavior is to separate these responsibilities: before running ambiguity detection, the backend should first ask the LLM whether the query is outside the KPI chatbot domain or violates the active chatbot `addon_prompt` constraints.

A rejected query should be treated the same as the existing out-of-scope flow. The pipeline should stop before ambiguity detection, SQL generation, and analysis, and return the user-facing message:

> Mohon maaf pertanyaan anda diluar konteks domain sistem atau pertanyaan anda melanggar aturan atau term of service yang telah ditetapkan

## Goals

- Add a dedicated scope/policy prompt that runs before ambiguity detection.
- Treat out-of-domain questions and `addon_prompt` violations as the same blocking outcome.
- Keep ambiguity detection focused on ambiguity only.
- Preserve session context handling so follow-up questions are not incorrectly rejected.
- Keep the existing `ClarificationService` out-of-scope response contract where possible.

## Non-goals

- Add a new API response type for addon policy violations.
- Add rule-based keyword filtering.
- Change NL-to-SQL, SQL guardrails, chart generation, or result analysis behavior.
- Refactor unrelated clarification or prompt code.

## Recommended Architecture

Use a two-stage LLM gate inside `AmbiguityDetectorService.detect_ambiguity()`.

### Stage 1: Scope and Policy Assessment

Add a new prompt builder in `template/promptTemplate.py`, for example:

```python
def build_scope_policy_assessment_prompt(
    user_query: str,
    user_role: str,
    kpi_context: str = "",
    addon_prompt: str | None = None,
    session_context: str | None = None,
) -> str:
    ...
```

The prompt should classify only whether the query must be blocked before the KPI pipeline continues. It checks:

1. The current question and session context.
2. The KPI/database domain from `DB_SCHEMA` and `kpi_context`.
3. The active chatbot addon constraints from `addon_prompt`.

The prompt must output strict JSON without markdown. The minimal contract used by the service is:

```json
{"is_out_of_scope": true}
```

or:

```json
{"is_out_of_scope": false}
```

It may include an internal reason field for logging and debugging, but the pipeline treats all rejection reasons as `is_out_of_scope=True`.

### Stage 2: Ambiguity Detection

If the scope/policy assessment returns `is_out_of_scope=false`, run the existing ambiguity detector prompt.

`build_ambiguity_assessment_prompt` should be simplified so it no longer performs scope or addon-policy checks. It should retain:

- session-context pre-resolution,
- AmbiSQL taxonomy,
- clarification question formatting,
- strict output JSON contract for ambiguity results.

The ambiguity result still includes `is_out_of_scope`, but after the split the ambiguity prompt should normally return `false` for that field because blocking scope/policy decisions happen earlier.

## Data Flow

1. `ClarificationService.process_user_query()` calls `AmbiguityDetectorService.detect_ambiguity()` with `user_query`, `user_role`, `kpi_context`, `addon_prompt`, and `session_context`.
2. `AmbiguityDetectorService.detect_ambiguity()` calls `_assess_scope_policy_with_llm()`.
3. If the precheck rejects the query, the service returns an `AmbiguityAssessmentResult` with:
   - `is_ambiguous=True`, so `ClarificationService` builds a blocking response,
   - `is_out_of_scope=True`,
   - `ambiguity_type="none"`,
   - empty detected ambiguities.
4. `ClarificationService._build_clarification_response_from_detection()` sees `is_out_of_scope=True` and returns `ClarificationMessageResponse(message_type="out_of_scope", is_out_of_scope=True)`.
5. The response text for that out-of-scope message is updated to the approved wording.
6. If the precheck allows the query, ambiguity detection runs as it does today.

## Error Handling

- If the precheck LLM call fails or returns invalid JSON, preserve current safe fallback behavior by treating the query as not ambiguous and not out-of-scope through the existing outer exception path.
- Log the precheck decision and reason when available.
- Do not proceed to ambiguity detection when the precheck explicitly rejects the query.

## Testing

Add or update focused tests in `tests/clarificationMechanism_test.py` and related prompt tests:

1. `build_scope_policy_assessment_prompt` includes the user query, role, schema/domain context, session context, and addon constraints.
2. Empty `addon_prompt` does not inject the addon constraint block.
3. `AmbiguityDetectorService.detect_ambiguity()` calls the scope/policy prompt before ambiguity detection.
4. When the precheck returns `is_out_of_scope=true`, ambiguity prompt builder and ambiguity LLM call are skipped.
5. When the precheck returns `is_out_of_scope=false`, the ambiguity prompt still runs.
6. Out-of-scope response text matches:
   `Mohon maaf pertanyaan anda diluar konteks domain sistem atau pertanyaan anda melanggar aturan atau term of service yang telah ditetapkan`.

## Design Review Notes

- The design keeps service cohesion: scope/policy gating remains separate from clarification-question generation.
- The design intentionally accepts one extra LLM call for valid queries to get a clean decision boundary.
- The design avoids a new public API shape because the user wants addon violations treated the same as out-of-scope.
