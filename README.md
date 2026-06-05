## Project Overview

FastAPI KPI chatbot backend. It ingests KPI data from Google Sheets, stores it in PostgreSQL, and answers role-scoped natural-language KPI questions through a structured RAG pipeline.

Main flow:
1. Optional ambiguity clarification before SQL generation
2. NL-to-SQL prompt + LLM generation
3. SQL guardrail validation
4. Async SQL execution
5. Optional chart generation
6. LLM result analysis

## Stack

- FastAPI 0.115 with async endpoints
- SQLAlchemy 2 async, asyncpg, Alembic
- PostgreSQL in runtime; SQLite/aiosqlite in tests
- JWT auth with role-based access (`admin`, `kepala_divisi`, `karyawan`)
- OpenAI-compatible LLM client (`openai` package)
- Google Sheets via service account (`gspread`, `google-auth`)
- APScheduler for ingestion jobs
- pytest, pytest-asyncio, pytest-html, Playwright report/PDF support

## Project Structure

```text
controller/   Request handlers; delegate to services
router/       FastAPI route registration
service/      Business logic and pipeline orchestration
repository/   Database/file persistence access
model/        SQLAlchemy models, plus SchedulerConfig Pydantic model
schema/       Pydantic request/response models
template/     LLM prompt builders and schema context
middleware/   JWT middleware and route authorization
utils/        Parsers, session context, lookup helpers
alembic/      Database migrations
tests/        Async integration/service tests
config/       Scheduler config manager
seeder/       User seeder
```

## Key Runtime Modules

- `main.py`: creates FastAPI app, installs JWT/CORS middleware, registers routers, starts/stops scheduler on lifespan.
- `configCredidential.py`: settings from `.env`.
- `databaseConfig.py`: async engine/session setup and `DATABASE_URL` normalization to `postgresql+asyncpg://`.
- `middleware/jwtMiddleware.py`: public-route bypass, JWT validation, RBAC.
- `service/chatService.py`: structured RAG orchestrator.
- `service/clarificationService.py`: clarification orchestration and answer handling.
- `service/ambiguityDetectorService.py`: LLM-only AmbiSQL-style ambiguity detection.
- `service/preferenceTreeService.py`: clarification preference tree context.
- `service/columnStatisticsService.py`: DB statistics for NL-to-SQL context.
- `service/sqlGuardRailsService.py`: generated SQL validation/sanitization.
- `service/graphicService.py`: matplotlib chart generation.
- `service/schedulerJobService.py`: APScheduler job lifecycle.
- `config/schedulerConfigManager.py` + `repository/schedulerRepository.py`: scheduler config stored as JSON, not database table.

## Data Model Notes

Core SQLAlchemy models:
- `User`: auth, role, division.
- `Chatbot`: active chatbot config per authority, including optional `addon_prompt` constraints.
- `ChatSession` / `ChatMessage`: chat history; sessions link to active chatbot.
- `ClarificationQuestion`: ambiguity questions, options, selected/free-text answers, message/session links.
- `KPIGroup`, `KPIMaster`, `KPITracker`: Google Sheets source metadata, KPI definitions, monthly tracker rows.
- `IngestionLog`: ingestion audit records.
- `RevokedToken`, `PasswordReset`: auth support.

`model/SchedulerConfig.py` is a Pydantic config model for file-backed scheduler settings. Do not treat it as a SQLAlchemy table.

## Chat Pipeline Details

`ChatService.process_query()` requires an active chatbot for the user authority. Its `addon_prompt` is threaded into ambiguity detection, NL-to-SQL, and analysis prompts.

Pipeline stages:
1. `Ambiguity Detection`: `ClarificationService` may return clarification questions and stop pipeline.
2. `nl_to_sql`: builds prompt with schema, role/division, addon prompt, and column statistics.
3. `sql_validation`: `SQLWireguardService` blocks unsafe SQL and enforces constraints.
4. `sql_execution`: `ChatQueryRepository.execute_read_query()` runs sanitized SQL with timeout.
5. `graphic_generation`: only runs when LLM visualization classifier says user requested chart.
6. `result_analysis`: LLM turns rows into narrative; 429 degrades to data-only message.

Keep ambiguity detection separate from clarification-question formatting/generation.

## Ingestion and Scheduler

Google Sheets ingestion uses service account credentials. Master and tracker ingestion have separate services:
- `service/kpiMasterIngestionService.py`
- `service/TrackeringestionService.py`

Scheduler config is file-backed through `SchedulerRepository`/`schedulerConfigManager`, then registered with `scheduler_job_service` during app lifespan when enabled.

## Commands

```bash
# setup
pip install -r requirement.txt
playwright install chromium

# run app
python main.py
# or
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# tests
pytest
pytest tests/chatPipeline_test.py -v
pytest -k "chatbot" -v
pytest --html=reports/report.html --self-contained-html

# migrations
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1
alembic history

# seed users
python -m seeder.userSeeder
```

CI runs Python 3.10, installs `requirement.txt`, installs Playwright browsers, creates `.env` from secrets, then runs `pytest`.

## Configuration

Environment comes from `.env` and `.env.example`.

Important variables:
- `DATABASE_URL`
- `GOOGLE_CREDENTIALS_PATH`
- `SECRET_KEY`, `REFRESH_SECRET_KEY`, `RESET_SECRET_KEY`
- `LLM_MODEL_API_KEY`, `LLM_MODEL_BASE_URL`
- `LLM_MODEL_NL_TO_SQL`, `LLM_MODEL_ANALYSIS`, `LLM_MODEL_DISAMBIGUATION`, `LLM_MODEL_GRAPHIC_CLASSIFIER`
- `CORS_ORIGINS`, optional `CORS_ORIGIN_REGEX`
- `SQL_MAX_LIMIT`, `SQL_MAX_SUBQUERY_DEPTH`, `SQL_EXECUTION_TIMEOUT`
- `RATE_LIMIT_PER_MINUTE`

## Code Patterns

- Use async/await for DB and external I/O.
- Keep controllers thin; put business logic in services.
- Use repositories for persistence access.
- Use Pydantic schemas for request/response boundaries.
- Raise `HTTPException` at API/service boundaries with user-safe messages.
- Avoid broad refactors while fixing specific behavior.
- Prefer direct deletion of dead code over compatibility shims.
- Default to no comments unless a non-obvious constraint needs explanation.

## Testing Patterns

- Tests use `pytest` and `pytest.mark.asyncio` for async cases.
- `conftest.py` sets up SQLite test DB and report hooks.
- Add or update focused tests near changed behavior.
- Chat pipeline behavior is covered by `tests/chatPipeline_test.py`, `tests/chatStreaming_test.py`, `tests/clarificationMechanism_test.py`, and `tests/chatbotAuthorityAddonPrompt_test.py`.
- Scheduler, ingestion, CRUD, and user/chatbot management have separate test files under `tests/`.

## Common Pitfalls

- Keep `DATABASE_URL` async-compatible; `databaseConfig.py` normalizes PostgreSQL URLs.
- Do not bypass `SQLWireguardService` for generated SQL.
- Do not assume scheduler config lives in DB; current runtime uses JSON-backed config.
- Do not run chat pipeline without active chatbot authority config.
- Preserve addon prompt propagation when changing chat/clarification prompts.
- Clarification can create multiple questions and supports `Lewati` / `Lainnya` options.
- Google Sheets service account must have read access to target sheets.
- Run Alembic migrations after pulling schema changes.

## API Docs

When app runs locally:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
