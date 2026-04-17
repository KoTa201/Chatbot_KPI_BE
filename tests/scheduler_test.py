"""
tests/scheduler_test.py
Detail test suite for scheduler repository, controller, and service behavior.
Run: pytest tests/scheduler_test.py -v
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from service.schedulerService import SchedulerService


def make_db() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


class TestSchedulerRepository:

    @pytest.mark.asyncio
    async def test_get_config_returns_none_when_empty(self):
        """get_config mengembalikan None jika belum ada config di DB."""
        from repository.schedulerRepository import SchedulerRepository

        db = make_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)

        repo = SchedulerRepository(db)
        config = await repo.get_config()

        assert config is None

    @pytest.mark.asyncio
    async def test_create_config_add_commit_refresh(self):
        """create_config harus add + commit + refresh object SchedulerConfigORM."""
        from repository.schedulerRepository import SchedulerRepository

        db = make_db()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        repo = SchedulerRepository(db)
        with patch.object(db, "add") as mock_add:
            config = await repo.create_config(
                interval_value=12,
                interval_unit="hours",
                is_enabled=True,
            )

        mock_add.assert_called_once_with(config)
        db.commit.assert_called_once()
        db.refresh.assert_called_once_with(config)
        assert config.interval_value == 12
        assert config.interval_unit == "hours"
        assert config.is_enabled is True

    @pytest.mark.asyncio
    async def test_create_config_rollback_and_raise_http_500(self):
        """Jika commit gagal, repository wajib rollback lalu melempar HTTP 500."""
        from repository.schedulerRepository import SchedulerRepository

        db = make_db()
        db.commit = AsyncMock(side_effect=Exception("db down"))
        db.rollback = AsyncMock()

        repo = SchedulerRepository(db)

        with pytest.raises(HTTPException) as exc_info:
            await repo.create_config(
                interval_value=1,
                interval_unit="days",
                is_enabled=True,
            )

        db.rollback.assert_called_once()
        assert exc_info.value.status_code == 500
        assert "Gagal simpan scheduler config" in exc_info.value.detail


class TestSchedulerService:

    def test_build_trigger_hours(self):
        """Interval hours harus diterjemahkan ke detik yang sesuai."""
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = SchedulerService()._build_trigger(12, "hours")
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.total_seconds() == 12 * 3600

    def test_build_trigger_days(self):
        """Interval days harus diterjemahkan ke detik yang sesuai."""
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = SchedulerService()._build_trigger(7, "days")
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.total_seconds() == 7 * 86400

    def test_build_trigger_months_converts_to_30_days(self):
        """Unit months dipetakan menjadi 30 hari per bulan."""
        from apscheduler.triggers.interval import IntervalTrigger

        trigger = SchedulerService()._build_trigger(2, "months")
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.total_seconds() == 60 * 86400

    @pytest.mark.asyncio
    async def test_register_job_enabled_adds_job(self):
        """register_job harus menambah job saat config enabled."""
        service = SchedulerService()
        config = SimpleNamespace(
            interval_value=1, interval_unit="hours", is_enabled=True)

        with (
            patch.object(service.scheduler, "get_job", return_value=None),
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            await service.register_job(config)

        mock_add_job.assert_called_once()
        kwargs = mock_add_job.call_args.kwargs
        assert kwargs["id"] == service.JOB_ID
        assert kwargs["replace_existing"] is True
        assert kwargs["misfire_grace_time"] == service.MISFIRE_GRACE_TIME

    @pytest.mark.asyncio
    async def test_register_job_disabled_does_not_add_job(self):
        """register_job tidak boleh add job jika scheduler dinonaktifkan."""
        service = SchedulerService()
        config = SimpleNamespace(
            interval_value=1, interval_unit="hours", is_enabled=False)

        with (
            patch.object(service.scheduler, "get_job", return_value=None),
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            await service.register_job(config)

        mock_add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_job_replaces_existing_job(self):
        """Jika job lama ada, register_job harus remove lalu add yang baru."""
        service = SchedulerService()
        config = SimpleNamespace(
            interval_value=1, interval_unit="days", is_enabled=True)

        with (
            patch.object(service.scheduler, "get_job",
                         return_value=MagicMock()),
            patch.object(service.scheduler, "remove_job") as mock_remove_job,
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            await service.register_job(config)

        mock_remove_job.assert_called_once_with(service.JOB_ID)
        mock_add_job.assert_called_once()

    def test_get_next_run_time_returns_none_when_job_missing(self):
        """get_next_run_time harus None ketika job scheduler belum ada."""
        service = SchedulerService()
        with patch.object(service.scheduler, "get_job", return_value=None):
            assert service.get_next_run_time() is None

    @pytest.mark.asyncio
    async def test_job_executes_at_scheduled_interval(self):
        """Scheduler mengeksekusi job sesuai interval waktu yang ditentukan (1 detik)."""
        from apscheduler.triggers.interval import IntervalTrigger

        service = SchedulerService()
        config = SimpleNamespace(
            interval_value=1, interval_unit="hours", is_enabled=True)
        run_times: list[datetime] = []

        async def fake_job() -> None:
            run_times.append(datetime.now(timezone.utc))

        service._run_ingestion_job = fake_job

        with patch.object(service, "_build_trigger", return_value=IntervalTrigger(seconds=1)):
            await service.register_job(config)

        started_at = datetime.now(timezone.utc)
        service.start_scheduler()
        try:
            await asyncio.sleep(1.4)
        finally:
            service.stop_scheduler()

        assert len(run_times) >= 1
        first_delay = (run_times[0] - started_at).total_seconds()
        assert 0.8 <= first_delay <= 2.2


class TestSchedulerController:

    @pytest.mark.asyncio
    async def test_create_config_save_and_register_scheduler_job(self):
        """create_config harus simpan config baru, register job, dan isi next_run_at."""
        from controller.schedulerController import SchedulerController

        db = make_db()
        controller = SchedulerController(db)

        mock_config = MagicMock()
        mock_config.id = "uuid-1"
        mock_config.interval_value = 12
        mock_config.interval_unit = "hours"
        mock_config.is_enabled = True
        mock_config.last_run_at = None
        mock_config.next_run_at = None
        next_run = datetime.now(timezone.utc)

        with (
            patch.object(controller.repo, "get_config",
                         new_callable=AsyncMock, return_value=None),
            patch.object(controller.repo, "create_config",
                         new_callable=AsyncMock, return_value=mock_config) as mock_create_config,
            patch.object(controller.scheduler_service,
                         "register_job", new_callable=AsyncMock) as mock_register_job,
            patch.object(controller.scheduler_service,
                         "get_next_run_time", return_value=next_run),
            patch.object(controller.repo, "update_run_times",
                         new_callable=AsyncMock) as mock_update_run_times,
        ):
            result = await controller.create_config(
                interval_value=12,
                interval_unit="hours",
                is_enabled=True,
            )

        mock_create_config.assert_called_once_with(
            interval_value=12,
            interval_unit="hours",
            is_enabled=True,
        )
        mock_register_job.assert_called_once_with(mock_config)
        mock_update_run_times.assert_called_once_with(next_run_at=next_run)
        assert result["interval_value"] == 12
        assert result["interval_unit"] == "hours"
        assert result["is_enabled"] is True
        assert result["next_run_at"] == next_run

    @pytest.mark.asyncio
    async def test_create_config_when_existing_returns_409(self):
        """create_config harus menolak bila config scheduler sudah ada."""
        from controller.schedulerController import SchedulerController

        db = make_db()
        controller = SchedulerController(db)

        with patch.object(controller.repo, "get_config", new_callable=AsyncMock, return_value=MagicMock()):
            with pytest.raises(HTTPException) as exc_info:
                await controller.create_config(interval_value=1, interval_unit="hours", is_enabled=True)

        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_trigger_now_runs_ingestion_job(self):
        """trigger_now harus mengeksekusi _run_ingestion_job saat config tersedia."""
        from controller.schedulerController import SchedulerController

        db = make_db()
        controller = SchedulerController(db)

        with (
            patch.object(controller.repo, "get_config",
                         new_callable=AsyncMock, return_value=MagicMock()),
            patch.object(controller.scheduler_service,
                         "_run_ingestion_job", new_callable=AsyncMock) as mock_run_ingestion,
        ):
            result = await controller.trigger_now()

        mock_run_ingestion.assert_called_once()
        assert result["message"] == "Ingestion triggered successfully."

    @pytest.mark.asyncio
    async def test_trigger_now_without_config_returns_404(self):
        """trigger_now harus return 404 jika config scheduler belum dibuat."""
        from controller.schedulerController import SchedulerController

        db = make_db()
        controller = SchedulerController(db)

        with patch.object(controller.repo, "get_config", new_callable=AsyncMock, return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await controller.trigger_now()

        assert exc_info.value.status_code == 404
