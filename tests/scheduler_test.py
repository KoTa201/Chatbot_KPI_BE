"""
tests/scheduler_test.py
Detail test suite for scheduler repository, controller, and service behavior.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from model.SchedulerConfig import SchedulerConfigModel
from service.schedulerService import SchedulerService
from config.schedulerConfigManager import SchedulerConfigManager


class TestSchedulerRepository:

    @pytest.mark.asyncio
    async def test_get_config_returns_default_config(self):
        """get_config selalu mengembalikan config (default jika file belum ada)."""
        from repository.schedulerRepository import SchedulerRepository

        mock_config = SchedulerConfigModel(
            interval_value=datetime(1900, 1, 28, 0, 0, 0),
            is_enabled=True,
        )
        with patch.object(SchedulerConfigManager, "get_config", new_callable=AsyncMock, return_value=mock_config):
            repo = SchedulerRepository()
            config = await repo.get_config()
            assert config is not None
            assert config.is_enabled is True

    @pytest.mark.asyncio
    async def test_update_config_saves_to_manager(self):
        """update_config harus memanggil save_config dengan perubahan yang diberikan."""
        from repository.schedulerRepository import SchedulerRepository

        existing = SchedulerConfigModel(
            interval_value=datetime(1900, 1, 28, 0, 0, 0),
            is_enabled=True,
        )
        repo = SchedulerRepository()
        repo.config = existing

        with patch.object(SchedulerConfigManager, "save_config", new_callable=AsyncMock) as mock_save:
            result = await repo.update_config({"is_enabled": False})

        mock_save.assert_called_once()
        assert result.is_enabled is False


class TestSchedulerService:

    def test_build_trigger_returns_cron_trigger(self):
        """_build_trigger harus menghasilkan CronTrigger."""
        from apscheduler.triggers.cron import CronTrigger

        iv = datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc)
        trigger = SchedulerService().job_service._build_trigger(iv)
        assert isinstance(trigger, CronTrigger)

    def test_build_trigger_fires_on_correct_day_and_hour(self):
        """CronTrigger harus fire pada hari dan jam yang benar tiap bulan."""
        from apscheduler.triggers.cron import CronTrigger

        iv = datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc)
        trigger = SchedulerService().job_service._build_trigger(iv)

        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        next_fire = trigger.get_next_fire_time(None, start)
        assert next_fire.day == 28
        assert next_fire.hour == 0
        assert next_fire.minute == 0

    @pytest.mark.asyncio
    async def test_auto_pause_if_december_pauses_in_december(self):
        """_auto_pause_if_december harus remove job dan set is_enabled=False di bulan Desember."""
        service = SchedulerService().job_service
        mock_repo = AsyncMock()
        mock_repo.get_config = AsyncMock()
        mock_repo.update_config = AsyncMock()
        december = datetime(2026, 12, 15, 0, 0, 0, tzinfo=timezone.utc)

        with (
            patch("service.schedulerJobService.SchedulerRepository", return_value=mock_repo),
            patch.object(service.scheduler, "get_job", return_value=MagicMock()),
            patch.object(service.scheduler, "remove_job") as mock_remove,
        ):
            await service._auto_pause_if_december(now=december)

        mock_repo.update_config.assert_called_once_with({"is_enabled": False})
        mock_remove.assert_called_once_with(service.JOB_ID)

    @pytest.mark.asyncio
    async def test_auto_pause_if_december_skips_non_december(self):
        """_auto_pause_if_december tidak boleh pause di bulan selain Desember."""
        service = SchedulerService().job_service

        with patch.object(service.scheduler, "remove_job") as mock_remove:
            june = datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
            await service._auto_pause_if_december(now=june)

        mock_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_job_enabled_adds_cron_job(self):
        """register_job harus menambah CronTrigger job saat config enabled."""
        from apscheduler.triggers.cron import CronTrigger

        service = SchedulerService().job_service
        config = SimpleNamespace(
            interval_value=datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc),
            is_enabled=True,
        )

        with (
            patch.object(service.scheduler, "get_job", return_value=None),
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            service.register_job(config)

        mock_add_job.assert_called_once()
        kwargs = mock_add_job.call_args.kwargs
        assert kwargs["id"] == service.JOB_ID
        assert kwargs["replace_existing"] is True
        assert isinstance(kwargs["trigger"], CronTrigger)

    @pytest.mark.asyncio
    async def test_register_job_disabled_does_not_add_job(self):
        """register_job tidak boleh add job jika scheduler dinonaktifkan."""
        service = SchedulerService().job_service
        config = SimpleNamespace(
            interval_value=datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc),
            is_enabled=False,
        )

        with (
            patch.object(service.scheduler, "get_job", return_value=None),
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            service.register_job(config)

        mock_add_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_job_replaces_existing_job(self):
        """Jika job lama ada, register_job harus remove lalu add yang baru."""
        service = SchedulerService().job_service
        config = SimpleNamespace(
            interval_value=datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc),
            is_enabled=True,
        )

        with (
            patch.object(service.scheduler, "get_job", return_value=MagicMock()),
            patch.object(service.scheduler, "remove_job") as mock_remove_job,
            patch.object(service.scheduler, "add_job") as mock_add_job,
        ):
            service.register_job(config)

        mock_remove_job.assert_called_once_with(service.JOB_ID)
        mock_add_job.assert_called_once()

    def test_get_next_run_time_returns_none_when_job_missing(self):
        """get_next_run_time harus None ketika job scheduler belum ada."""
        service = SchedulerService().job_service
        with patch.object(service.scheduler, "get_job", return_value=None):
            assert service.get_next_run_time() is None


class TestSchedulerController:

    @pytest.mark.asyncio
    async def test_get_config_returns_default(self):
        """get_config harus selalu mengembalikan config (tidak pernah None)."""
        from controller.schedulerController import SchedulerController

        controller = SchedulerController()
        mock_config = SchedulerConfigModel(
            interval_value=datetime(1900, 1, 28, 0, 0, 0),
            is_enabled=True,
        )

        with patch.object(controller.service.repo, "get_config",
                          new_callable=AsyncMock, return_value=mock_config):
            result = await controller.get_config()

        assert result is not None
        assert result.is_enabled is True

    @pytest.mark.asyncio
    async def test_update_config_updates_and_registers_job(self):
        """update_config harus simpan perubahan, register job, dan isi next_run_at."""
        from controller.schedulerController import SchedulerController

        controller = SchedulerController()

        iv = datetime(1900, 1, 28, 0, 0, 0, tzinfo=timezone.utc)
        mock_config = SchedulerConfigModel(
            interval_value=iv,
            is_enabled=True,
        )
        next_run = datetime.now(timezone.utc)

        class DummyPayload:
            def model_dump(self, exclude_none=False):
                return {"is_enabled": False}

        with (
            patch.object(controller.service.repo, "update_config",
                         new_callable=AsyncMock, return_value=mock_config),
            patch.object(controller.service.job_service,
                         "register_job") as mock_register_job,
            patch.object(controller.service.job_service,
                         "get_next_run_time", return_value=next_run),
            patch.object(controller.service.repo, "update_run_times",
                         new_callable=AsyncMock) as mock_update_run_times,
        ):
            result = await controller.update_config(DummyPayload())

        mock_register_job.assert_called_once_with(mock_config)
        mock_update_run_times.assert_called_once_with(next_run_at=next_run)

    @pytest.mark.asyncio
    async def test_trigger_now_runs_ingestion_job(self):
        """trigger_now harus mengeksekusi run_ingestion_job."""
        from controller.schedulerController import SchedulerController

        controller = SchedulerController()

        with patch.object(controller.service.job_service,
                          "run_ingestion_job", new_callable=AsyncMock) as mock_run_ingestion:
            result = await controller.trigger_now()

        mock_run_ingestion.assert_called_once()
        assert result["message"] == "Ingestion triggered successfully."
