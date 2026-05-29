# Public Chart URL Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace chart base64 payloads with session-scoped PNG files served from `/public`, and append deterministic chart links to chat narratives.

**Architecture:** `GraphicSeervice` generates PNG files under `public/charts/{session_id}/` and returns a URL instead of base64. `ChatService` passes `session_id` into graphic generation, appends the returned URL to narrative text, and exposes `graphic_image_url` while keeping `graphic_image_base64=None` for client compatibility. `main.py` mounts FastAPI static files at `/public`.

**Tech Stack:** FastAPI `StaticFiles`, Python `pathlib`, `uuid`, matplotlib, pytest, pytest-asyncio, Pydantic.

---

## File Structure

- Modify `service/graphicService.py`
  - Responsibility: chart data preparation, matplotlib rendering, writing chart PNG files, returning chart metadata.
- Modify `service/chatService.py`
  - Responsibility: orchestrate pipeline, pass `session_id` to chart generation, append chart URL to narrative, return URL in response.
- Modify `schema/chatSchema.py`
  - Responsibility: response contract; add `graphic_image_url`, keep legacy `graphic_image_base64` nullable.
- Modify `main.py`
  - Responsibility: mount static public folder.
- Modify `tests/chatPipeline_test.py`
  - Responsibility: verify pipeline returns chart URL, not base64, and appends URL to response narrative.
- Create `tests/graphicService_test.py` if absent
  - Responsibility: verify graphic service persists PNG to session-scoped path and returns public URL.

---

### Task 1: Add file-backed chart generation to graphic service

**Files:**
- Modify: `service/graphicService.py`
- Create: `tests/graphicService_test.py`

- [ ] **Step 1: Write failing test for saved PNG and URL**

Create or append to `tests/graphicService_test.py`:

```python
from uuid import UUID

from service.graphicService import GraphicSeervice


def test_generate_graphic_saves_png_in_session_folder(tmp_path):
    service = GraphicSeervice(public_dir=tmp_path)
    session_id = UUID("00000000-0000-0000-0000-000000000101")

    result = service.generateGraphic(
        query_result=[
            {"bulan": 1, "total_realisasi": 120},
            {"bulan": 2, "total_realisasi": 90},
        ],
        chart_type="bar",
        session_id=session_id,
    )

    assert result.chart_type == "bar"
    assert result.image_url.startswith(
        "/public/charts/00000000-0000-0000-0000-000000000101/"
    )
    assert result.image_url.endswith(".png")

    saved_file = tmp_path / result.image_url.removeprefix("/public/")
    assert saved_file.exists()
    assert saved_file.read_bytes().startswith(b"\x89PNG")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graphicService_test.py::test_generate_graphic_saves_png_in_session_folder -q
```

Expected: FAIL because `GraphicSeervice.__init__()` does not accept `public_dir`, `generateGraphic()` does not accept `session_id`, and `GraphicResult` has no `image_url`.

- [ ] **Step 3: Implement minimal file-backed result**

Modify `service/graphicService.py` imports and dataclass:

```python
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

import pandas as pd
from fastapi import HTTPException, status
```

Replace `GraphicResult`:

```python
@dataclass
class GraphicResult:
    chart_type: str
    image_url: str
```

Replace `GraphicSeervice.__init__` header/body start:

```python
class GraphicSeervice:
    """Service untuk membuat grafik dari data hasil query SQL."""

    def __init__(self, public_dir: str | Path = "public"):
        self.public_dir = Path(public_dir)
        self.chart_public_prefix = "/public/charts"
        self.supported_chart_types = {"bar", "pie", "donut"}
```

Change `generateGraphic` signature:

```python
    def generateGraphic(
        self,
        query_result: list[dict],
        chart_type: str = "bar",
        session_id: UUID | None = None,
    ) -> GraphicResult:
```

Replace the base64 save block:

```python
            image_buffer = io.BytesIO()
            figure.savefig(image_buffer, format="png", dpi=140, bbox_inches="tight")
            image_bytes = image_buffer.getvalue()
```

Replace the return after `finally`:

```python
        image_url = self._save_chart_image(image_bytes=image_bytes, session_id=session_id)
        return GraphicResult(chart_type=chart_type, image_url=image_url)
```

Add helper inside `GraphicSeervice` before `_prepare_chart_data`:

```python
    def _save_chart_image(self, image_bytes: bytes, session_id: UUID | None) -> str:
        session_folder = str(session_id) if session_id is not None else "unsessioned"
        file_name = f"{uuid.uuid4()}.png"
        relative_path = Path("charts") / session_folder / file_name
        output_path = self.public_dir / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return f"/public/{relative_path.as_posix()}"
```

Remove unused `base64` import.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graphicService_test.py::test_generate_graphic_saves_png_in_session_folder -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/graphicService.py tests/graphicService_test.py
git commit -m "feat: save generated charts as public files"
```

---

### Task 2: Return chart URL through chat pipeline and append it to narrative

**Files:**
- Modify: `schema/chatSchema.py`
- Modify: `service/chatService.py`
- Modify: `tests/chatPipeline_test.py`

- [ ] **Step 1: Write failing pipeline test for URL response and narrative append**

Modify `tests/chatPipeline_test.py` existing `test_process_query_success_with_visualization`.

Replace the graphic mock block:

```python
    monkeypatch.setattr(
        chat_service_module.graphic_service,
        "generateGraphic",
        lambda query_result, chart_type, session_id=None: GraphicResult(
            chart_type=chart_type,
            image_url=f"/public/charts/{session_id}/chart-1.png",
        ),
    )
```

Replace assertions at end of test:

```python
    expected_url = f"/public/charts/{SESSION_VISUAL}/chart-1.png"
    assert response.message == f"Analisa dengan grafik.\n\nGrafik: {expected_url}"
    assert response.graphic_chart_type == "pie"
    assert response.graphic_image_url == expected_url
    assert response.graphic_image_base64 is None
    assert _stage_by_name(response, "graphic_generation").status == "success"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/chatPipeline_test.py::test_process_query_success_with_visualization -q
```

Expected: FAIL because `GraphicResult` no longer accepts `image_base64` in existing code paths and `ChatResponse` has no `graphic_image_url`.

- [ ] **Step 3: Add response field**

Modify `schema/chatSchema.py` `ChatResponse`:

```python
class ChatResponse(BaseModel):
    session_id: UUID
    message: str                        # Jawaban naratif dari LLM
    # Jika ada pertanyaan klarifikasi
    clarification_questions: list[ClarificationQuestionResponse] | None = None
    generated_sql: str | None = None    # Hanya ditampilkan jika show_sql=True
    graphic_chart_type: str | None = None
    graphic_image_url: str | None = None
    graphic_image_base64: str | None = None
    rows_returned: int | None = None
    execution_time_ms: int | None = None
    pipeline_stages: list[PipelineStageInfo] = Field(default_factory=list)
```

- [ ] **Step 4: Pass session_id into graphic generation**

Modify `_run_graphic_generation_stage` signature in `service/chatService.py`:

```python
    def _run_graphic_generation_stage(
        self,
        stages: list[PipelineStageInfo],
        query_result: list[dict],
        chart_type: str,
        session_id: UUID,
    ) -> GraphicResult | None:
```

Modify its service call:

```python
            graphic_result = graphic_service.generateGraphic(
                query_result=query_result,
                chart_type=chart_type,
                session_id=session_id,
            )
```

Modify call site in `process_query`:

```python
                graphic_result = self._run_graphic_generation_stage(
                    stages=stages,
                    query_result=query_result,
                    chart_type=visualization_decision.chart_type or "bar",
                    session_id=session_id,
                )
```

- [ ] **Step 5: Append chart URL after analysis**

Add helper near other static helpers in `service/chatService.py`:

```python
    @staticmethod
    def _append_graphic_url(narrative: str, graphic_result: GraphicResult | None) -> str:
        if graphic_result is None:
            return narrative
        return f"{narrative}\n\nGrafik: {graphic_result.image_url}"
```

Modify after `_run_result_analysis_stage` call in `process_query`:

```python
            narrative = self._append_graphic_url(narrative, graphic_result)
```

Modify `ChatResponse` construction:

```python
                graphic_chart_type=graphic_result.chart_type if graphic_result else None,
                graphic_image_url=graphic_result.image_url if graphic_result else None,
                graphic_image_base64=None,
```

- [ ] **Step 6: Run test to verify it passes**

Run:

```bash
pytest tests/chatPipeline_test.py::test_process_query_success_with_visualization -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add schema/chatSchema.py service/chatService.py tests/chatPipeline_test.py
git commit -m "feat: return public chart urls from chat pipeline"
```

---

### Task 3: Mount public folder for static chart access

**Files:**
- Modify: `main.py`
- Create or modify: `tests/main_test.py`

- [ ] **Step 1: Write failing test for static mount**

Create or append to `tests/main_test.py`:

```python
from fastapi.staticfiles import StaticFiles

from main import app


def test_public_static_files_are_mounted():
    public_route = next((route for route in app.routes if getattr(route, "path", None) == "/public"), None)

    assert public_route is not None
    assert isinstance(public_route.app, StaticFiles)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/main_test.py::test_public_static_files_are_mounted -q
```

Expected: FAIL because `/public` is not mounted.

- [ ] **Step 3: Mount public directory**

Modify imports in `main.py`:

```python
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
```

Add after app creation and before middleware/router includes:

```python
PUBLIC_DIR = Path("public")
PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/main_test.py::test_public_static_files_are_mounted -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main.py tests/main_test.py
git commit -m "feat: serve public chart files"
```

---

### Task 4: Full regression verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused chart and chat tests**

Run:

```bash
pytest tests/graphicService_test.py tests/chatPipeline_test.py tests/main_test.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run existing related repository test**

Run:

```bash
pytest tests/chatSessionRepository_test.py -q
```

Expected: `2 passed`.

- [ ] **Step 3: Inspect public output behavior manually through unit result**

Run:

```bash
pytest tests/graphicService_test.py::test_generate_graphic_saves_png_in_session_folder -q
```

Expected: PASS and test verifies PNG magic bytes.

- [ ] **Step 4: Commit any missed test updates**

If any tracked files changed during verification:

```bash
git status --short
git add <changed-files>
git commit -m "test: verify public chart url flow"
```

If no tracked files changed, do not commit.

---

## Self-Review

- Spec coverage:
  - Session-scoped chart files: Task 1.
  - Public URL response: Task 2.
  - Narrative link append: Task 2.
  - Static public serving: Task 3.
  - Regression tests: Task 4.
- Placeholder scan: no `TBD`, `TODO`, or incomplete steps.
- Type consistency:
  - `GraphicResult.image_url` used consistently in service, schema, tests.
  - `session_id: UUID` passed from `ChatService.process_query()` to `_run_graphic_generation_stage()` to `GraphicSeervice.generateGraphic()`.
  - Legacy `graphic_image_base64` remains nullable and set to `None`.
