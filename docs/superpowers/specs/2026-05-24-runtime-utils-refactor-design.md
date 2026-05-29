#

Runtime Utils Refactor Design

## Scope

Refactor only repeated runtime helper functions into the existing `utils/` package. Do not move Pydantic schemas, business validators, auth token parsing/decoding, domain constants, or repository/service business logic.

## Utility modules

Create these utility modules:

- `utils/pagination.py`
  - `validate_page(page: int) -> int`
  - `validate_limit(limit: int, *, max_limit: int = 100) -> int`
  - `calculate_total_pages(total: int, limit: int) -> int`
- `utils/datetime.py`
  - `utc_now() -> datetime`
- `utils/responses.py`
  - `json_response(status_code: int, detail: str) -> Response`

## Migration targets

Update repeated runtime helper usage only:

- Replace duplicated pagination validation in controllers that check `page < 1` or `limit < 1 or limit > 100`.
- Replace duplicated total-page ceiling logic where it matches existing behavior.
- Replace direct `datetime.now(timezone.utc)` runtime call sites where a zero-argument callable preserves behavior.
- Replace JWT middleware local JSON response helper with `utils.responses.json_response`.

## Non-goals

- Do not move `PaginationInfo` schema classes from KPI master/tracker schemas.
- Do not change response payload shape, HTTP status codes, validation messages unless required to keep helper behavior consistent with existing callers.
- Do not change ambiguity detection, clarification formatting, SQL generation, guardrails, ingestion logic, or scheduler behavior.
- Do not extract domain-specific constants such as group types.

## Testing

Run focused tests covering changed controllers and auth middleware where available, then run full `pytest` if feasible. If full suite cannot run in reasonable time, report focused test results and blocker.
