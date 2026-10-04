"""Run with --once for a bounded batch, otherwise periodically until SIGTERM."""

import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import TrainingSettings, get_training_settings
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.jobs.telegram_delivery import classify_failure
from fitcoach.infrastructure.jobs.worker_loop import run_periodically
from fitcoach.repository.training_repository import TrainingConflictError

logger = logging.getLogger(__name__)


async def run_batch(
    repository: PostgresTrainingRepository, bot: Bot, settings: TrainingSettings
) -> int:
    if not settings.reminders_enabled:
        logger.info("Training reminders are disabled")
        return 0
    policy = settings.to_retry_policy()
    await repository.enqueue_due(utc_now())
    delivered = 0
    for _ in range(policy.batch_size):
        delivery = await repository.claim_reminder(utc_now(), policy.sending_timeout)
        if delivery is None:
            break
        if delivery.attempts > policy.max_attempts:
            logger.error("Reminder %s exhausted attempts after a worker interruption", delivery.id)
            await repository.finish_reminder(delivery, failed=True)
            continue
        try:
            await bot.send_message(
                chat_id=delivery.chat_id,
                message_thread_id=delivery.thread_id,
                text=Constants.TRAINING_DUE_MESSAGE,
            )
        except TelegramError as error:
            outcome = classify_failure(error, delivery.attempts, policy, utc_now())
            logger.log(
                logging.ERROR if outcome.failed else logging.WARNING,
                "Reminder %s not delivered to chat %s: retry_at=%s failed=%s",
                delivery.id,
                delivery.chat_id,
                outcome.retry_at,
                outcome.failed,
                exc_info=True,
            )
            await repository.finish_reminder(
                delivery, retry_at=outcome.retry_at, failed=outcome.failed
            )
            if outcome.unexpected:
                raise
            continue
        try:
            await repository.finish_reminder(delivery)
        except TrainingConflictError:
            logger.exception("Reminder %s was delivered but its lease expired", delivery.id)
            raise
        delivered += 1
    logger.info("Training reminder batch finished: delivered=%s", delivered)
    return delivered


async def run(once: bool) -> None:
    configure_logging()
    settings = get_training_settings()

    async def batch(session: AsyncSession, bot: Bot) -> int:
        return await run_batch(PostgresTrainingRepository(session), bot, settings)

    await run_periodically("Training reminders", batch, settings.interval_seconds, once)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
