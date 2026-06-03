# General Clarification Options Design

## Context

The clarification pipeline currently uses LLM prompts to detect ambiguity and generate user-facing clarification choices. For a query such as `bagaimana perkembangan kpi andi`, the ambiguity assessment prompt includes a few-shot example that lists specific employee candidates such as `Andi Pratama`, `Andi Susanto`, and `Andi Wijaya`.

Those names are only examples, but the model can imitate them as if they were real database records. This makes clarification options look authoritative even when the values may not exist in the database. Specific value matching should stay in the NL-to-SQL and SQL execution stages, where schema, column statistics, and actual query results can determine whether data exists.

## Goal

Make clarification options for ambiguous person/entity names more general and clear, without inventing database-specific names, IDs, divisions, or values.

For the example query `bagaimana perkembangan kpi andi`, clarification should still detect ambiguity, but AmbiValue choices should be intent-level options such as:

- Search employees whose name contains `Andi`.
- Treat `Andi` as the full employee name.
- Let the user provide the intended employee name manually.

## Non-Goals

- Do not query the database during clarification choice generation.
- Do not add service-level post-processing for AmbiValue choices.
- Do not merge ambiguity detection with clarification question formatting.
- Do not change NL-to-SQL guardrails or SQL execution behavior.

## Proposed Approach

Use a prompt-focused change in `template/promptTemplate.py`.

### Ambiguity Assessment Prompt

Update `build_ambiguity_assessment_prompt()` so `AmbiValue` handling distinguishes between actual evidence and missing evidence:

- If evidence provides real candidate records, the prompt may list those candidates.
- If evidence does not provide real candidate records, the prompt must not invent specific names, IDs, divisions, or database values.
- For person/entity terms without concrete evidence, generate general intent options instead.

Revise the few-shot example for `bagaimana perkembangan andi` so the `andi` ambiguity no longer lists fake employees. The example should show general options while preserving the `AmbiView` ambiguity for `perkembangan`.

### Clarification Choice Generation Prompt

Update `build_clarification_choice_generation_prompt()` with a guardrail that the choice generator must not introduce specific names, IDs, divisions, or database values that are not present in the input description.

The generator may rewrite input options into clearer user-facing sentences, but it must not add new facts.

## Expected Data Flow

1. User asks `bagaimana perkembangan kpi andi`.
2. Ambiguity detection identifies:
   - `andi` as `AmbiValue` because it cannot be uniquely resolved.
   - `perkembangan` as `AmbiView` because the intended KPI view or metric is unclear.
3. The `AmbiValue` description contains general intent choices instead of fake employee candidates.
4. Clarification choice generation turns those descriptions into user-facing options without adding new database-specific values.
5. User selection or manual input is folded into the rewritten query.
6. NL-to-SQL uses existing schema/statistics rules, including flexible name matching via `UPPER(u.full_name) LIKE`.
7. SQL execution and result analysis handle whether matching records actually exist.

## Testing

Update focused tests near the existing clarification prompt tests.

Test coverage should verify that:

- The ambiguity assessment prompt no longer contains fake employee examples such as `Andi Susanto`.
- The ambiguity assessment prompt explicitly instructs AmbiValue options to stay general when real evidence is unavailable.
- The example for `bagaimana perkembangan andi` keeps both the name ambiguity and the `perkembangan` metric ambiguity.
- The choice generation prompt forbids introducing names, IDs, divisions, or specific database values not present in the input description.

## Risks and Mitigations

- **Risk:** Prompt-only changes still depend on LLM compliance.
  **Mitigation:** Make the rule explicit in both ambiguity assessment and choice generation prompts, and cover it with prompt-content tests.

- **Risk:** Removing specific candidate examples could make AmbiValue options too vague.
  **Mitigation:** Use clear intent-level choices that map naturally to later NL-to-SQL behavior.

- **Risk:** Real candidate evidence may become available later and should remain usable.
  **Mitigation:** The rule only forbids invented values. It still allows listing candidates that are explicitly present in evidence.
