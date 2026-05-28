# RAGAS KPI Answer Quality Design

## Goal
Raise RAGAS answer correctness and answer relevancy for KPI target/progress questions by changing prompt behavior only.

## Scope
This change affects runtime answers and eval answers. It does not add deterministic row enrichment or repository-layer status computation.

## Architecture
`template/promptTemplate.py` remains the single prompt source. The NL-to-SQL prompt will make latest-month KPI progress queries return the fields needed for analysis. The analysis prompt will answer directly and concisely instead of always printing a full table and generic insight section.

## NL-to-SQL Behavior
For questions about target achievement, near-target status, progress, performance, `achieve`, `partial`, or `fail`, the generated SQL should return raw KPI fields for analysis:

- `kt.bulan_num`
- `km.kpi_name`
- `kt.realisasi`
- `km.target`
- `km.achieve`
- `km.partial`
- `km.fail`
- `kt.keterangan`

For latest-period wording such as `sampai bulan terakhir`, `terbaru`, or `latest`, SQL should filter to the latest relevant `bulan_num` and must not filter by direct equality against `km.achieve` or `km.partial`.

## Analysis Behavior
The analysis prompt should:

- Answer user question first.
- Keep response concise.
- Avoid mandatory full Markdown table output.
- Avoid generic `Insight dari Data` unless user asks.
- For KPI target/progress questions, compare `realisasi` with `target` when both are comparable numeric values or both use `TRL N` format.
- Treat numeric equality (`realisasi == target`) and TRL equality (`TRL N == TRL N`) as target achieved.
- Use `achieve`, `partial`, and `fail` as threshold descriptors, not as required literal labels in `keterangan`.
- Never say status is unknown only because `keterangan` does not include `ACHIEVE` when structured `realisasi` and `target` prove target achievement.

## Testing
Update `tests/promptTemplate_test.py` to assert:

- NL-to-SQL prompt still forbids direct `kt.realisasi` equality comparison against threshold descriptor columns.
- NL-to-SQL prompt asks for latest-month raw KPI fields.
- Analysis prompt instructs direct concise answers.
- Analysis prompt includes numeric and `TRL N` comparison guidance.
- Analysis prompt no longer requires full table first.

## Verification
Run:

```bash
pytest tests/promptTemplate_test.py -v
python evals/ragas/runner.py
```

Success target: prompt tests pass, and RAGAS answer correctness/relevancy improve toward at least 0.8 for `team_kpi_progress_against_target`.
