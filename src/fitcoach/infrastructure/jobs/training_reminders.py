"""Run with --once for a bounded batch, otherwise periodically until SIGTERM."""

import argparse
import asyncio
import logging
import signal
from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError
from telegram import Bot
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import TrainingSettings, get_training_settings
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.database.session import close_database, get_session_factory
from fitcoach.repository.training_repository import TrainingConflictError

logger = logging.getLogger(__name__)


async def run_batch(
    repository: PostgresTrainingRepository, bot: Bot, settings: TrainingSettings
) -> int:
    if not settings.reminders_enabled:
        logger.info("Training reminders are disabled")
        return 0
    await repository.enqueue_due(utc_now())
    delivered = 0
    for _ in range(100):
        delivery = await repository.claim_reminder(utc_now())
        if delivery is None:
            break
        try:
            await bot.send_message(
                chat_id=delivery.chat_id,
                message_thread_id=delivery.thread_id,
                text=Constants.TRAINING_DUE_MESSAGE,
            )
        except RetryAfter as error:
            delay = error.retry_after
            seconds = delay.total_seconds() if isinstance(delay, timedelta) else float(delay)
            logger.warning("Reminder %s rate limited; delay=%s", delivery.id, seconds)
            await repository.finish_reminder(
                delivery,
                retry_at=utc_now() + timedelta(seconds=max(1, seconds)),
                failed=delivery.attempts >= settings.reminder_max_attempts,
            )
        except (BadRequest, Forbidden):
            logger.exception(
                "Reminder %s cannot be delivered to chat %s", delivery.id, delivery.chat_id
            )
            await repository.finish_reminder(delivery, failed=True)
        except NetworkError:
            logger.exception("Transient Telegram failure for reminder %s", delivery.id)
            await repository.finish_reminder(
                delivery,
                retry_at=utc_now() + timedelta(seconds=min(3600, 30 * 2**delivery.attempts)),
                failed=delivery.attempts >= settings.reminder_max_attempts,
            )
        except TelegramError:
            logger.exception("Unexpected Telegram failure for reminder %s", delivery.id)
            await repository.finish_reminder(delivery, failed=True)
            raise
        else:
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
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    bot = await get_bot()
    try:
        while not stop.is_set():
            try:
                async with get_session_factory()() as session:
                    await run_batch(PostgresTrainingRepository(session), bot, settings)
            except SQLAlchemyError:
                logger.exception("Training reminder database/schema unavailable")
                if once:
                    raise
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.reminder_interval_seconds)
            except TimeoutError:
                continue
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        await bot.shutdown()
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
