"""
tests/kpiTrackerBatch_test.py
Tests for POST /api/v1/ingest/google-sheets/batch
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from router.kpiTrackerRouter import router as tracker_router
from schema.kpiTrackerSchema import (
    BatchTrackerIngestionResponse,
    BulkIngestionResponse,
    UrlIngestionResult,
)

# ── App fixture ─────────────────────────────────────────────────────────── #

@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(tracker_router, prefix="/api/v1/ingest")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Constant ─────────────────────────────────────────────────────────────── #

_BATCH_ROUTE = "controller.kpiTrackerController.KPITrackerController.ingest_batch_from_google_sheets"


# ── Tests ────────────────────────────────────────────────────────────────── #

@pytest.mark.asyncio
async def test_batch_returns_results_for_each_url(client):
    """Each URL in the request gets its own UrlIngestionResult in the response."""
    urls = [
        "https://docs.google.com/spreadsheets/d/aaa/edit",
        "https://docs.google.com/spreadsheets/d/bbb/edit",
    ]
    expected_response = BatchTrackerIngestionResponse(
        total_urls=2,
        succeeded=2,
        failed=0,
        results=[
            UrlIngestionResult(
                sheet_url=urls[0], status="success",
                total_sheets_processed=2, grand_total_rows=10,
                grand_ingested=10, grand_failed=0, sheets=[],
            ),
            UrlIngestionResult(
                sheet_url=urls[1], status="partial",
                total_sheets_processed=1, grand_total_rows=5,
                grand_ingested=3, grand_failed=2, sheets=[],
            ),
        ],
    )

    with patch(_BATCH_ROUTE, new_callable=AsyncMock, return_value=expected_response):
        response = await client.post(
            "/api/v1/ingest/google-sheets/batch",
            json={"sheet_urls": urls, "skip_on_error": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_urls"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["results"]) == 2
    assert data["results"][0]["sheet_url"] == urls[0]
    assert data["results"][0]["status"] == "success"
    assert data["results"][1]["sheet_url"] == urls[1]
    assert data["results"][1]["status"] == "partial"


@pytest.mark.asyncio
async def test_batch_empty_url_list_rejected(client):
    """Request with empty sheet_urls list should return 422."""
    response = await client.post(
        "/api/v1/ingest/google-sheets/batch",
        json={"sheet_urls": [], "skip_on_error": True},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_too_many_urls_rejected(client):
    """Request with more than 20 URLs should return 422."""
    urls = [f"https://docs.google.com/spreadsheets/d/{i}/edit" for i in range(21)]
    response = await client.post(
        "/api/v1/ingest/google-sheets/batch",
        json={"sheet_urls": urls, "skip_on_error": True},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_one_url_fails_others_still_succeed(client):
    """A single failed URL should appear as failed=1, not abort the whole batch."""
    urls = [
        "https://docs.google.com/spreadsheets/d/ok/edit",
        "https://docs.google.com/spreadsheets/d/bad/edit",
    ]
    expected_response = BatchTrackerIngestionResponse(
        total_urls=2,
        succeeded=1,
        failed=1,
        results=[
            UrlIngestionResult(
                sheet_url=urls[0], status="success",
                total_sheets_processed=1, grand_total_rows=5,
                grand_ingested=5, grand_failed=0, sheets=[],
            ),
            UrlIngestionResult(
                sheet_url=urls[1], status="error",
                error="Could not access spreadsheet",
            ),
        ],
    )

    with patch(_BATCH_ROUTE, new_callable=AsyncMock, return_value=expected_response):
        response = await client.post(
            "/api/v1/ingest/google-sheets/batch",
            json={"sheet_urls": urls},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["succeeded"] == 1
    assert data["failed"] == 1
    assert data["results"][1]["status"] == "error"
    assert "Could not access" in data["results"][1]["error"]
