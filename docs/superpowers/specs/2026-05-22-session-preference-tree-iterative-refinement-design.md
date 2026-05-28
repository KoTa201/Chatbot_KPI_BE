# Session Preference Tree and Iterative Refinement Design

## Context

The current ambiguity pipeline detects ambiguities, asks clarification questions, accepts answers, and performs one rewrite before continuing to the Text-to-SQL pipeline. The PRD also calls for a preference update module and iterative refinement. This design adds those pieces without creating a new preference table.

Preferences are scoped to a single chat session. They should not influence future sessions.

## Goals

- Save clarification answers in a session-scoped preference tree.
- Use the tree and clarification evidence to refine the original query.
- Re-check the rewritten query for remaining ambiguity.
- Continue refinement until no ambiguity remains, the user skips remaining ambiguity, or a max round limit is reached.
- Preserve separation between ambiguity detection and clarification-question generation.

## Non-goals

- No cross-session or global user preference memory.
- No new preference table.
- No revival of the deleted clarification question generator service.
- No automatic SQL generation inside the refinement module.

## Architecture

`ClarificationService` remains the orchestrator, but the responsibilities stay logically separate:

1. **Ambiguity Detection**
   - Identifies unresolved ambiguities from a query and context.
   - Does not own preference updates or query rewriting.

2. **CQ Generation**
   - Formats the detector-provided question/options into API responses.
   - The deleted standalone CQ generator service is not revived because generation is currently fulfilled by the detector output (`question_set`) plus lightweight response formatting. This avoids duplicating LLM calls while preserving the CQ responsibility boundary.

3. **Preference Update**
   - Builds an in-memory session preference tree from the current round's QA set.
   - Uses NodeMerge for semantic conflict resolution on leaf QA lists.

4. **Query Refinement**
   - Rewrites the original query from additional information.
   - Does not mutate the preference tree.

5. **Evidence-Augmented Re-check**
   - Runs ambiguity detection again on the rewritten query plus serialized preference tree and round number.
   - Returns another clarification response if ambiguity remains and the round limit has not been reached.
   - Otherwise returns the disambiguated query to the normal RAG pipeline.

## Preference tree structure

```text
TreeNode:
  - level1: ambiguity type (e.g. "AmbiSchema")
  - level2: ambiguous phrase (e.g. "terbaik")
  - node_type: "root" | "level1" | "level2" | "leaf"
  - children: dict of child TreeNodes
  - qa_list: list of {question, answer} — only on leaf nodes

PreferenceTree:
  - root: TreeNode (root)
  - leaf_map: dict[(level1, level2) → leaf TreeNode]
    used as a fast lookup index
  - update_tree(qa_set): entry point, iterates qa_set and calls add_qa() per item
  - add_qa(level1, level2, question, answer): ensures nodes exist down to leaf, then calls NodeMerge
```

Tree hierarchy:

```text
root
└── level1 (ambiguity type)
    └── level2 (ambiguous phrase)
        └── leaf
            └── qa_list [{question, answer}, ...]
```

Example coverage for all PRD ambiguity types:

```text
root
├── AmbiSchema
│   └── terbaik
│       └── leaf: [{question: "'Terbaik' merujuk ke metrik apa?", answer: "Achievement %"}]
├── AmbiValue
│   └── teknologi
│       └── leaf: [{question: "'Teknologi' cocok dengan entri mana?", answer: "IT & Digital"}]
├── AmbiIntent
│   └── tampilkan sales per tim
│       └── leaf: [{question: "Data ingin dikelompokkan, diurutkan, atau difilter?", answer: "Dikelompokkan per tim"}]
├── AmbiSource
│   └── kurs konversi sales
│       └── leaf: [{question: "Kurs mana yang digunakan?", answer: "Kurs BI pada tanggal transaksi"}]
├── AmbiContext
│   └── data terbaru
│       └── leaf: [{question: "'Terbaru' merujuk ke periode apa?", answer: "Bulan terakhir yang tersedia"}]
├── AmbiFallacy
│   └── program X tahun 2024
│       └── leaf: [{question: "Program X tidak tersedia pada 2024, lanjut dengan alternatif?", answer: "Gunakan tahun pertama program tersedia"}]
└── AmbiRef
    └── tahun lalu
        └── leaf: [{question: "'Tahun lalu' merujuk ke periode mana?", answer: "Calendar Year 2025"}]
```

For LLM-sourced types (`AmbiSource`, `AmbiContext`, `AmbiFallacy`), `level2` is still the ambiguous phrase or concept from the question. There is no structural difference between LLM-sourced and database-sourced types in the tree.

## Data flow

1. User sends an original query.
2. `ClarificationService.process_user_query()` builds KPI evidence/context and calls ambiguity detection.
3. If clarification is needed, questions are returned with ambiguity type, ambiguous phrase/concept, question, options, detection metadata, and round.
4. User submits clarification answers.
5. `ClarificationService.handle_clarification_response()` validates answer ids, builds the current round's full QA set, and calls `PreferenceTree.update_tree(qa_set)` once.
6. Query refinement uses the preserved original query and additional information from non-skipped answers, raw additional constraints, evidence, and the current in-memory tree.
7. The rewritten query is checked again for ambiguity with evidence/tree context.
8. If ambiguity remains and the round limit is not reached, the service returns a new clarification response.
9. If no ambiguity remains, or the loop stops, the service returns `QueryDisambiguationResult` and the normal RAG pipeline continues.

The current implementation stores the original query through an overloaded/truncated `ambiguous_phrase` field. The implementation must preserve the full original query from the request path and stop relying on `ambiguous_phrase` as the source of truth.

## Stateless preference tree

The `PreferenceTree` is stateless and lives only in memory for one request-response cycle.

- No persistence to database, cache, or file.
- No new table, no new column, no migration.
- The tree is built fresh each time from the clarification answers provided in the current request.
- `update_tree()` is called once per `handle_clarification_response()` invocation with the full QA set for that session round.
- The tree is serialized only for query refinement and evidence-augmented re-check inside the same request.

## Prompt templates

### Query refinement prompt

The rewrite prompt must use this behavior:

```text
## Task
To combine an `original_question` with `additional_information` into a single, coherent, and complete new question that is logically sound and easy to understand.

## Core Principles
1. Absolute Preservation: You MUST preserve ALL constraints, details, and intents from the `original_question`. Nothing from the original should be omitted or altered unless it is directly and explicitly contradicted by the `additional_information`.
2. Full Integration: You MUST seamlessly integrate ALL new requirements and constraints from the `additional_information` into the new question.
3. Conflict Resolution: If a piece of `additional_information` directly conflicts with a part of the `original_question`, the `additional_information` takes precedence and should be used to update or replace the conflicting part. This is the only scenario where original information may be modified.
4. Natural Language: The final output must be a single, natural-sounding question, not a list of criteria.

## Response Format
- Return only the text of the rewritten question.
- Do not include any preamble, labels, or explanations.
```

Project mapping:

- `original_question` is the preserved original user query.
- `additional_information` is a natural-language evidence block built from selected clarification answers, `Lainnya` free text, additional constraints, and relevant session tree entries.
- `Lewati` answers are recorded in the tree but excluded from rewrite constraints.
- `Lainnya` uses `free_text` as the authoritative answer.

### NodeMerge prompt

`NodeMerge` is called inside `add_qa()` on the leaf node. It replaces latest-record-wins conflict handling entirely.

```text
## Task
Merge a new question-answer pair into an existing list of question-answer pairs.

## Input
- old_list: existing list of objects, each with a `question` and `answer` field.
- new_pair: object with a `question` and `answer` field.

## Merge Instructions
1. Compare the `question` field of `new_pair` with each item in `old_list`. If any question in `old_list` has the same or highly similar meaning as `new_pair` (same intent, possibly different wording), treat it as a conflict.
2. If there is a conflict, remove the conflicting item and replace it with `new_pair`.
3. If there is no conflict, append `new_pair` at the end.
4. Ensure the output list contains no duplicate questions by meaning.
5. Return ONLY the merged list as a valid JSON array: [{"question": "...", "answer": "..."}, ...]
6. Do NOT return any explanation or text outside the JSON array.
```

## Additional constraints pipeline

Additional constraints travel separately from preference tree updates.

- Additional constraints are not passed through `NodeMerge`.
- They are appended directly to `additional_information` as raw text.
- Ambiguity detection runs on the rewritten query that incorporates additional constraints, independently of preference tree processing.

## Lewati / Abstain behavior

- `Lewati` answers are recorded in the tree with `answer = "Lewati"` so the request has a complete in-memory record.
- `Lewati` answers are excluded from `additional_information` passed to query refinement.
- Using `Lewati` answers to improve future CQ generation quality is out of scope for this iteration.

## Ambiguity dependency ordering

Ambiguity types can have dependencies. For example, `AmbiIntent` should be resolved before `AmbiSchema` and `AmbiValue` when the intended operation affects which schema elements or values are relevant.

The iterative refinement loop handles this naturally: each round runs ambiguity detection on the refined query, so dependent ambiguities can surface in later rounds without explicit ordering logic.

## Evidence-augmented re-check

The re-check receives the rewritten query, serialized preference tree, and round number. This is an intentional improvement over the base AmbiSQL paper.

- It reduces false positives where the LLM would re-flag already-resolved ambiguities.
- It keeps already answered QA context available without cross-session memory.
- This behavior is not described in the paper and is an explicit design addition.

## Stop conditions

The refinement loop stops when one of these is true:

1. Ambiguity detection reports no remaining ambiguity.
2. The max refinement round limit is reached.
3. The user skips all remaining ambiguity questions.
4. Detection or refinement fails and the safe fallback returns the best rewritten query to the normal RAG pipeline.

## Error handling

- If LLM refinement fails, use the deterministic fallback that appends non-skipped answer information to the original query.
- If NodeMerge fails or returns invalid JSON, append the new pair deterministically after removing exact duplicate questions.
- If ambiguity re-check fails, continue with the rewritten query rather than blocking the user.
- If an answer references an unknown question id, return the existing validation error.

## Testing

- Unit test session preference tree construction from multiple clarification answers.
- Unit test `NodeMerge` prompt parsing and deterministic fallback.
- Unit test additional-information formatting for selected answers, `Lainnya`, `Lewati`, and additional constraints.
- Unit test the QuestionRefine prompt builder preserves the required prompt behavior.
- Integration test ambiguous query → clarification → answer → tree update → query rewrite → ambiguity re-check.
- Regression test skipped answers are recorded but not included as rewrite constraints.

## Implementation boundaries

- Keep ambiguity detection separate from clarification-question generation.
- Do not recreate `clarificationQuestionGeneratorService.py`.
- Keep changes focused in `ClarificationService`, `ClarificationRepository`, clarification schemas/models, prompt template, and tests.
