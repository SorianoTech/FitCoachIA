from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from telegram import Bot
from telegram.error import Forbidden, NetworkError, RetryAfter, TelegramError

from fitcoach.infrastructure.config.settings import TrainingSettings
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.jobs import training_reminders
from fitcoach.infrastructure.jobs.training_reminders import run_batch
from fitcoach.repository.training_repository import ReminderDelivery

_NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(training_reminders, "utc_now", lambda: _NOW)


def _settings(**values: object) -> TrainingSettings:
    return TrainingSettings(_env_file=None, reminders_enabled=True, **values)


@pytest.mark.asyncio
async def test_disabled_worker_does_not_query_database() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    assert await run_batch(repository, AsyncMock(spec=Bot), TrainingSettings(_env_file=None)) == 0
    repository.enqueue_due.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivery_preserves_thread_and_records_success() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    delivery = ReminderDelivery(1, 7, 22, 1)
    repository.claim_reminder.side_effect = [delivery, None]
    bot = AsyncMock(spec=Bot)
    assert await run_batch(repository, bot, _settings()) == 1
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 22
    repository.finish_reminder.assert_awaited_once_with(delivery)


@pytest.mark.asyncio
async def test_claim_uses_the_configured_sending_timeout() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    repository.claim_reminder.return_value = None

    await run_batch(repository, AsyncMock(spec=Bot), _settings(sending_timeout_seconds=60))

    repository.claim_reminder.assert_awaited_once_with(_NOW, timedelta(seconds=60))


@pytest.mark.asyncio
async def test_batch_stops_at_the_configured_size() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    repository.claim_reminder.side_effect = lambda *_: ReminderDelivery(1, 7, None, 1)

    assert await run_batch(repository, AsyncMock(spec=Bot), _settings(batch_size=2)) == 2

    assert repository.claim_reminder.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NetworkError("offline"), RetryAfter(5), Forbidden("blocked")])
async def test_failures_are_persisted_without_retry_loop(error: Exception) -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    repository.claim_reminder.side_effect = [ReminderDelivery(1, 7, None, 5), None]
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = error
    assert await run_batch(repository, bot, _settings()) == 0
    assert repository.finish_reminder.await_args.kwargs["failed"]


@pytest.mark.asyncio
async def test_network_error_is_retried_with_the_configured_delay() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    delivery = ReminderDelivery(1, 7, None, 1)
    repository.claim_reminder.side_effect = [delivery, None]
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = NetworkError("offline")

    await run_batch(repository, bot, _settings(retry_delay_seconds=10))

    repository.finish_reminder.assert_awaited_once_with(
        delivery, retry_at=_NOW + timedelta(seconds=20), failed=False
    )


@pytest.mark.asyncio
async def test_rate_limit_waits_what_telegram_asks() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    delivery = ReminderDelivery(1, 7, None, 1)
    repository.claim_reminder.side_effect = [delivery, None]
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = RetryAfter(42)

    await run_batch(repository, bot, _settings())

    repository.finish_reminder.assert_awaited_once_with(
        delivery, retry_at=_NOW + timedelta(seconds=42), failed=False
    )


@pytest.mark.asyncio
async def test_exhausted_delivery_after_an_interruption_is_not_sent() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    delivery = ReminderDelivery(1, 7, None, 4)
    repository.claim_reminder.side_effect = [delivery, None]
    bot = AsyncMock(spec=Bot)

    await run_batch(repository, bot, _settings(max_attempts=3))

    bot.send_message.assert_not_awaited()
    repository.finish_reminder.assert_awaited_once_with(delivery, failed=True)


@pytest.mark.asyncio
async def test_unexpected_telegram_error_is_recorded_and_propagated() -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    delivery = ReminderDelivery(1, 7, None, 1)
    repository.claim_reminder.side_effect = [delivery, None]
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = TelegramError("boom")

    with pytest.raises(TelegramError):
        await run_batch(repository, bot, _settings())

    repository.finish_reminder.assert_awaited_once_with(delivery, retry_at=None, failed=True)
