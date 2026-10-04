import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fitcoach.infrastructure.jobs import worker_loop
from fitcoach.infrastructure.jobs.worker_loop import run_periodically


@pytest.fixture
def resources(monkeypatch: pytest.MonkeyPatch) -> tuple[AsyncMock, MagicMock, AsyncMock]:
    """Fake bot, DB session and shutdown hook; signal handlers are not available on Windows."""
    bot = AsyncMock()
    session = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    close_database = AsyncMock()
    monkeypatch.setattr(worker_loop, "get_bot", AsyncMock(return_value=bot))
    monkeypatch.setattr(worker_loop, "get_session_factory", lambda: factory)
    monkeypatch.setattr(worker_loop, "close_database", close_database)
    return bot, session, close_database


def _without_signal_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", lambda *_: None)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda *_: True)


@pytest.mark.asyncio
async def test_once_runs_a_single_batch_and_releases_resources(
    monkeypatch: pytest.MonkeyPatch, resources: tuple[AsyncMock, MagicMock, AsyncMock]
) -> None:
    _without_signal_handlers(monkeypatch)
    bot, session, close_database = resources
    batch = AsyncMock(return_value=1)

    await run_periodically("Test", batch, interval_seconds=10, once=True)

    batch.assert_awaited_once_with(session, bot)
    bot.shutdown.assert_awaited_once()
    close_database.assert_awaited_once()


@pytest.mark.asyncio
async def test_once_propagates_database_errors_and_still_releases_resources(
    monkeypatch: pytest.MonkeyPatch, resources: tuple[AsyncMock, MagicMock, AsyncMock]
) -> None:
    _without_signal_handlers(monkeypatch)
    bot, _, close_database = resources
    batch = AsyncMock(side_effect=SQLAlchemyError("schema missing"))

    with pytest.raises(SQLAlchemyError):
        await run_periodically("Test", batch, interval_seconds=10, once=True)

    bot.shutdown.assert_awaited_once()
    close_database.assert_awaited_once()


@pytest.mark.asyncio
async def test_periodic_mode_survives_database_errors(
    monkeypatch: pytest.MonkeyPatch, resources: tuple[AsyncMock, MagicMock, AsyncMock]
) -> None:
    _without_signal_handlers(monkeypatch)
    bot, _, _ = resources
    # Third tick aborts the loop so the test ends.
    batch = AsyncMock(side_effect=[SQLAlchemyError("down"), 1, RuntimeError("stop test")])

    with pytest.raises(RuntimeError, match="stop test"):
        await run_periodically("Test", batch, interval_seconds=0, once=False)

    assert batch.await_count == 3
    bot.shutdown.assert_awaited_once()
