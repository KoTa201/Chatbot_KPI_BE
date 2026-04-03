"""
tests/scheduler_test.py
Unit tests for scheduler repository and service.
Run: pytest tests/scheduler_test.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession


def make_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


@pytest.mark.asyncio
async def test_scheduler_repo_get_config_returns_none_when_empty():
    """get_config must return None when no row exists."""
    from repository.schedulerRepository import SchedulerRepository

    db = make_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    repo = SchedulerRepository(db)
    config = await repo.get_config()
    assert config is None


@pytest.mark.asyncio
async def test_scheduler_repo_create_stores_config():
    """create_config must add and commit a SchedulerConfigORM row."""
    from repository.schedulerRepository import SchedulerRepository

    db = make_db()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    repo = SchedulerRepository(db)
    with patch.object(db, "add") as mock_add:
        result = await repo.create_config(
            sheet_url="https://docs.google.com/spreadsheets/d/X",
            interval_value=12,
            interval_unit="hours",
            is_enabled=True,
        )
        mock_add.assert_called_once()
        db.commit.assert_called_once()


def test_build_trigger_hours():
    """_build_trigger must return IntervalTrigger with correct hours kwarg."""
    from service.schedulerService import _build_trigger
    from apscheduler.triggers.interval import IntervalTrigger

    trigger = _build_trigger(12, "hours")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 12 * 3600


def test_build_trigger_months_converts_to_days():
    """Months must be converted to days*30."""
    from service.schedulerService import _build_trigger
    from apscheduler.triggers.interval import IntervalTrigger

    trigger = _build_trigger(1, "months")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 30 * 86400


def test_build_trigger_days():
    """Days must map to IntervalTrigger days."""
    from service.schedulerService import _build_trigger
    from apscheduler.triggers.interval import IntervalTrigger

    trigger = _build_trigger(7, "days")
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 7 * 86400


@pytest.mark.asyncio
async def test_scheduler_controller_create_config():
    """create_config must save to DB and register job."""
    from controller.schedulerController import SchedulerController

    db = make_db()
    controller = SchedulerController(db)

    mock_config = MagicMock()
    mock_config.id = "uuid-1"
    mock_config.sheet_url = "https://docs.google.com/spreadsheets/d/X"
    mock_config.interval_value = 12
    mock_config.interval_unit = "hours"
    mock_config.is_enabled = True
    mock_config.last_run_at = None
    mock_config.next_run_at = None

    with (
        patch.object(controller.repo, "get_config", new_callable=AsyncMock, return_value=None),
        patch.object(controller.repo, "create_config", new_callable=AsyncMock, return_value=mock_config),
        patch("controller.schedulerController.register_job", new_callable=AsyncMock),
        patch("controller.schedulerController.get_next_run_time", return_value=None),
        patch.object(controller.repo, "update_run_times", new_callable=AsyncMock),
    ):
        result = await controller.create_config(
            sheet_url="https://docs.google.com/spreadsheets/d/X",
            interval_value=12,
            interval_unit="hours",
            is_enabled=True,
        )
        controller.repo.create_config.assert_called_once()
        assert result["interval_value"] == 12
