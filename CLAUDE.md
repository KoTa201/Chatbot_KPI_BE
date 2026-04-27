# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI-based chatbot backend for KPI (Key Performance Indicator) tracking and analysis. The system uses a structured RAG (Retrieval-Augmented Generation) pipeline to convert natural language queries into SQL, execute them against PostgreSQL, and provide AI-powered analysis with optional visualization.

## Development Commands

### Running the Application
```bash
# Start development server with hot reload
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Or using the entry point defined in pyproject.toml
uvicorn main:app --reload
```

### Database Operations
```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback migration
alembic downgrade -1

# View migration history
alembic history

# View current version
alembic current
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/chatPipeline_test.py

# Run with coverage
pytest --cov=.

# Run async tests specifically
pytest tests/ -v
```

### Dependencies
```bash
# Install dependencies
pip install -r requirement.txt

# Or using uv (if available)
uv sync
```

## Architecture

### Core Pipeline (Chat Service)
The main chatbot follows a 6-stage pipeline orchestrated by `ChatService`:

1. **Stage 0 - Ambiguity Detection & Clarification**: Detects ambiguous queries using LLM, generates clarifying questions if needed
2. **Stage 1 - NL-to-SQL**: Converts natural language to SQL using LLM (GPT-4o)
3. **Stage 2 - SQL Validation**: Validates generated SQL against security rules using SQLWireguardService
4. **Stage 3 - SQL Execution**: Executes validated SQL against PostgreSQL with timeout protection
5. **Stage 4 - Graphic Generation**: Optional visualization generation (bar/pie/donut charts) if requested
6. **Stage 5 - Result Analysis**: Converts query results into natural language narrative using LLM

### Layer Structure
- **Router**: FastAPI route definitions (`router/`)
- **Controller**: Request handling and business logic coordination (`controller/`)
- **Service**: Core business logic and orchestration (`service/`)
- **Repository**: Database access layer using SQLAlchemy async (`repository/`)
- **Model**: SQLAlchemy ORM models (`model/`)
- **Schema**: Pydantic models for request/response validation (`schema/`)
- **Template**: Prompt templates for LLM interactions (`template/`)
- **Middleware**: JWT authentication and CORS (`middleware/`)
- **Utils**: Helper utilities and parsers (`utils/`)

### Key Services

**LLM Service** (`service/llmService.py`):
- Wraps LLM API (OpenAI-compatible)
- Handles NL-to-SQL conversion, result analysis, and visualization decisions
- Implements retry logic and error handling

**Clarification Service** (`service/clarificationService.py`):
- Orchestrates ambiguity detection and clarification flow
- Limits clarifications to 1 per query to prevent loops
- Provides fallback disambiguation when LLM unavailable

**SQL Wireguard Service** (`service/sqlWireguardService.py`):
- Validates generated SQL for security
- Blocks dangerous operations (INSERT, UPDATE, DELETE, DROP, etc.)
- Enforces role-based access control

**Chat Service** (`service/chatService.py`):
- Main orchestrator for the RAG pipeline
- Manages session context and audit logging
- Handles pipeline errors gracefully

### Database Configuration

The project uses PostgreSQL with SQLAlchemy async:
- Connection pooling configured in `databaseConfig.py`
- Async driver: `postgresql+asyncpg://`
- Migrations managed via Alembic
- Schema defined in `model/` directory

### Authentication

JWT-based authentication implemented in:
- `middleware/jwtMiddleware.py`: JWT validation middleware
- `service/authService.py`: Authentication logic
- `controller/authController.py`: Auth endpoints

### Environment Variables

Key environment variables (see `.env.example`):
- `DATABASE_URL`: PostgreSQL connection string
- `LLM_API_KEY`: LLM API key
- `LLM_BASE_URL`: LLM endpoint
- `SECRET_KEY`: JWT signing key
- `GOOGLE_CREDENTIALS_PATH`: Google Sheets service account credentials

### Prompt Engineering

Prompts are centralized in `template/promptTemplate.py`:
- `build_nl_to_sql_prompt()`: Schema-first NL-to-SQL conversion with few-shot examples
- `build_analysis_prompt()`: Result analysis with strict anti-hallucination rules
- `build_ambiguity_assessment_prompt()`: Ambiguity detection
- `build_clarifying_question_prompt()`: Clarification question generation
- `build_query_disambiguation_prompt()`: Query disambiguation

### Testing Strategy

Tests are organized by functionality in `tests/`:
- `chatPipeline_test.py`: End-to-end pipeline testing
- `clarificationMechanism_test.py`: Clarification flow testing
- `chatbotManagement_test.py`: Chatbot CRUD operations
- `kpiGroupCRUD_test.py`: KPI group management
- `kpiMasterIngestion_test.py`: KPI master data ingestion

### Important Patterns

**Async/Await**: All database operations and external API calls use async/await pattern with SQLAlchemy async sessions.

**Error Handling**: Services raise `HTTPException` with appropriate status codes. Pipeline errors are caught and converted to user-friendly messages.

**Audit Logging**: All chat interactions are logged to `chatbot_audit_log` table for tracking and debugging.

**Session Management**: Chat sessions are tracked with UUIDs, allowing conversation history and context management.

**Role-Based Access**: Different user roles (admin, hrd, kepala_divisi, karyawan) have different data access scopes enforced at multiple layers.

**Timeout Protection**: SQL execution has configurable timeout to prevent long-running queries.

**Fallback Strategies**: LLM calls have fallback mechanisms for graceful degradation when services are unavailable.