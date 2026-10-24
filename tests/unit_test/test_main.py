import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from fitcoach import main
from fitcoach.infrastructure.config.settings import SchedulerSettings
from fitcoach.infrastructure.database.session import get_session
from fitcoach.infrastructure.vectordb.session import get_vector_session
from fitcoach.main import app


class TestAppEndpoints:
    def test_root_returns_service_metadata(self) -> None:
        response = TestClient(app).get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "online"

    def test_health_reports_liveness(self) -> None:
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

    def test_readiness_checks_both_database_dependencies(self) -> None:
        session = AsyncMock()
        vector_session = AsyncMock()
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_vector_session] = lambda: vector_session
        try:
            response = TestClient(app).get("/ready")
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(get_vector_session, None)

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
        session.execute.assert_awaited_once()
        vector_session.execute.assert_awaited_once()

    def test_readiness_returns_503_when_a_database_is_unavailable(self) -> None:
        session = AsyncMock()
        vector_session = AsyncMock()
        vector_session.execute.side_effect = SQLAlchemyError("database unavailable")
        app.dependency_overrides[get_session] = lambda: session
        app.dependency_overrides[get_vector_session] = lambda: vector_session
        try:
            response = TestClient(app, raise_server_exceptions=False).get("/ready")
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(get_vector_session, None)

        assert response.status_code == 503
        assert response.json() == {"detail": "Required database dependencies are unavailable"}


class TestScheduler:
    @pytest.fixture
    def scheduler_class(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        instance = MagicMock()
        stopped = asyncio.Event()

        async def run(stop: asyncio.Event) -> None:
            await stop.wait()
            stopped.set()

        instance.run = run
        instance.stopped = stopped
        scheduler_class = MagicMock(return_value=instance)
        monkeypatch.setattr(main, "JobScheduler", scheduler_class)
        monkeypatch.setattr(main, "get_bot", AsyncMock())
        monkeypatch.setattr(main, "get_session_factory", MagicMock())
        monkeypatch.setattr(main, "get_training_settings", MagicMock())
        monkeypatch.setattr(main, "get_evaluation_settings", MagicMock())
        return scheduler_class

    @pytest.mark.asyncio
    async def test_a_disabled_scheduler_starts_no_task(self, scheduler_class: MagicMock) -> None:
        assert await main._start_scheduler(SchedulerSettings(_env_file=None)) is None

        scheduler_class.assert_not_called()
        await main._stop_scheduler(None)

    @pytest.mark.asyncio
    async def test_an_enabled_scheduler_runs_until_it_is_stopped(
        self, scheduler_class: MagicMock
    ) -> None:
        started = await main._start_scheduler(SchedulerSettings(_env_file=None, enabled=True))

        assert started is not None
        _, task = started
        await asyncio.sleep(0)
        assert not task.done()

        await main._stop_scheduler(started)

        assert task.done()
        assert scheduler_class.return_value.stopped.is_set()

    @pytest.mark.asyncio
    async def test_stopping_surfaces_a_scheduler_that_crashed(
        self, scheduler_class: MagicMock
    ) -> None:
        async def crash(stop: asyncio.Event) -> None:
            raise RuntimeError("scheduler crashed")

        scheduler_class.return_value.run = crash
        started = await main._start_scheduler(SchedulerSettings(_env_file=None, enabled=True))
        assert started is not None

        with pytest.raises(RuntimeError, match="crashed"):
            await main._stop_scheduler(started)
