# AmbiSQL Ambiguity Detector Design

## Goal

Align the ambiguity detection flow with the AmbiSQL-style prompt from `PRD_Ambiguity_Check_KPI_TextToSQL.md` while keeping the existing internal response contract compatible with the current clarification pipeline.

## Scope

- Replace the current ambiguity assessment prompt with a paper-aligned prompt that accepts user question, database schema, and evidence.
- Keep `AmbiguityDetectorService` focused on detecting ambiguity candidates only.
- Keep clarification-question generation in `ClarificationQuestionGeneratorService`.
- Add database support for storing whether level-1 ambiguity is LLM-sourced.

Out of scope:

- `AmbiSource`, because this project always retrieves source data from the database.
- Changing API response shape to paper-native `question_set`.
- Moving CQ generation into the detector.

## Taxonomy

The detector will support these level-2 ambiguity labels:

- `AmbiSchema`
- `AmbiValue`
- `AmbiIntent`
- `AmbiContext`
- `AmbiFallacy`
- `AmbiRef`
- `none`

`AmbiIntent` covers cases where the query lacks keywords that clarify the intended operation, such as whether a phrase means ordering, grouping, filtering, ranking, or aggregation.

Level-1 ambiguity will not be stored as a string. It will be represented as `is_ambiguity_level1_type_llm`:

- `true` for `LLM-sourced ambiguity`
- `false` for `Database-sourced ambiguity`

## Prompt Design

`build_ambiguity_assessment_prompt()` will be rewritten around the AmbiSQL-style task:

- Inputs: `Question`, `Schema`, and `Evidence`.
- Evidence contains user-provided clarifications from previous turns.
- The prompt explicitly says that `Abstain` means the ambiguity should not be identified again.
- The prompt returns strict JSON:

```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "string",
      "level_1_label": "Database-sourced ambiguity | LLM-sourced ambiguity",
      "level_2_label": "AmbiSchema | AmbiValue | AmbiIntent | AmbiContext | AmbiFallacy | AmbiRef",
      "description": {
        "options": ["string"]
      }
    }
  ]
}
```

## Service Mapping

`AmbiguityDetectorService` will parse paper-style output and map it into the existing `AmbiguityAssessmentResult`:

- `has_ambiguity` and non-empty `question_set` determine `is_ambiguous`.
- `question_set[].level_2_label` maps to `DetectedAmbiguity.ambiguity_type`.
- `question_set[].description.options` maps to candidate options for downstream CQ generation.
- `question_set[].question` is carried as an optional detector-suggested question, but final CQ shaping remains in `ClarificationQuestionGeneratorService`.
- `is_ambiguity_level1_type_llm` is added to metadata and persisted through the clarification log model.

The detector will not generate final user-facing CQ copy. It only preserves ambiguity candidates and raw options.

## Database Change

Add nullable boolean column `is_ambiguity_level1_type_llm` to the clarification log table/model used by the existing ambiguity mechanism.

Migration behavior:

- Existing rows get `NULL` because historical level-1 type is unknown.
- New rows store `true` for LLM-sourced ambiguity and `false` for database-sourced ambiguity.

## Error Handling

- Empty or invalid LLM responses keep the current safe fallback: not ambiguous.
- Fenced or wrapped JSON remains supported.
- If `question_set` is empty, the result is not ambiguous.
- If an item has an unsupported level-2 label, it is skipped rather than coerced into another type.

## Testing

Add or update tests for:

- Parsing valid AmbiSQL `has_ambiguity/question_set` output.
- Empty `question_set` returning not ambiguous.
- Mapping `description.options` into downstream candidate options.
- Mapping level-1 labels into `is_ambiguity_level1_type_llm`.
- Ensuring `AmbiSource` is not accepted.
- Ensuring detector and CQ generator responsibilities remain separate.
