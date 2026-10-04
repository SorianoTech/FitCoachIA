from unittest.mock import AsyncMock

import pytest
from telegram import Bot
from telegram.error import Forbidden, NetworkError, RetryAfter

from fitcoach.infrastructure.config.settings import TrainingSettings
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.jobs.training_reminders import run_batch
from fitcoach.repository.training_repository import ReminderDelivery


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
    assert (
        await run_batch(repository, bot, TrainingSettings(_env_file=None, reminders_enabled=True))
        == 1
    )
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 22
    repository.finish_reminder.assert_awaited_once_with(delivery)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NetworkError("offline"), RetryAfter(5), Forbidden("blocked")])
async def test_failures_are_persisted_without_retry_loop(error: Exception) -> None:
    repository = AsyncMock(spec=PostgresTrainingRepository)
    repository.claim_reminder.side_effect = [ReminderDelivery(1, 7, None, 5), None]
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = error
    assert (
        await run_batch(repository, bot, TrainingSettings(_env_file=None, reminders_enabled=True))
        == 0
    )
    assert repository.finish_reminder.await_args.kwargs["failed"]
