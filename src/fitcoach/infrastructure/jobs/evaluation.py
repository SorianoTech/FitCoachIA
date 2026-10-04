"""Weekly satisfaction polls: --once for a bounded batch, otherwise periodically until SIGTERM."""

import argparse
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import EvaluationSettings, get_evaluation_settings
from fitcoach.infrastructure.database.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from fitcoach.infrastructure.jobs.telegram_delivery import classify_failure
from fitcoach.infrastructure.jobs.worker_loop import run_periodically
from fitcoach.repository.evaluation_repository import (
    EvaluationConflictError,
    EvaluationDelivery,
    EvaluationRepository,
)

logger = logging.getLogger(__name__)


def poll_question(week: int, goal: str | None) -> str:
    label = Constants.TRAINING_GOAL_LABELS.get(goal or "")
    if label is None:
        return Constants.EVALUATION_POLL_QUESTION_NO_GOAL.format(week=week)
    return Constants.EVALUATION_POLL_QUESTION.format(week=week, goal=label.lower())


async def run_batch(
    repository: EvaluationRepository, bot: Bot, settings: EvaluationSettings
) -> int:
    if not settings.enabled:
        logger.info("Evaluation polls are disabled")
        return 0
    policy = settings.to_retry_policy()
    sent = 0
    for _ in range(policy.batch_size):
        delivery = await repository.claim(utc_now(), policy.sending_timeout)
        if delivery is None:
            break
        if delivery.attempts > policy.max_attempts:
            logger.error(
                "Evaluation %s exhausted attempts after a worker interruption", delivery.id
            )
            await repository.finish(delivery, failed=True)
            continue
        await _close_previous(bot, delivery)
        try:
            message = await bot.send_poll(
                chat_id=delivery.chat_id,
                message_thread_id=delivery.thread_id,
                question=poll_question(delivery.week_number, delivery.goal),
                options=Constants.EVALUATION_POLL_OPTIONS,
                is_anonymous=False,
                allows_multiple_answers=False,
                allows_revoting=False,
            )
        except TelegramError as error:
            outcome = classify_failure(error, delivery.attempts, policy, utc_now())
            logger.log(
                logging.ERROR if outcome.failed else logging.WARNING,
                "Evaluation %s not delivered to chat %s: retry_at=%s failed=%s",
                delivery.id,
                delivery.chat_id,
                outcome.retry_at,
                outcome.failed,
                exc_info=True,
            )
            await repository.finish(delivery, retry_at=outcome.retry_at, failed=outcome.failed)
            if outcome.unexpected:
                raise
            continue
        if message.poll is None:
            logger.error("Evaluation %s: Telegram answered without a poll", delivery.id)
            await repository.finish(delivery, failed=True)
            continue
        try:
            await repository.mark_sent(delivery, message.poll.id, message.message_id, utc_now())
        except EvaluationConflictError:
            logger.exception("Evaluation %s was sent but its lock expired", delivery.id)
            raise
        sent += 1
    logger.info("Evaluation batch finished: sent=%s", sent)
    return sent


async def _close_previous(bot: Bot, delivery: EvaluationDelivery) -> None:
    # Best effort: failing to close the old poll must not block the new one.
    if delivery.previous_message_id is None:
        return
    try:
        await bot.stop_poll(chat_id=delivery.chat_id, message_id=delivery.previous_message_id)
    except TelegramError:
        logger.warning(
            "Evaluation %s could not close previous poll message %s",
            delivery.id,
            delivery.previous_message_id,
            exc_info=True,
        )


async def run(once: bool) -> None:
    configure_logging()
    settings = get_evaluation_settings()

    async def batch(session: AsyncSession, bot: Bot) -> int:
        return await run_batch(PostgresEvaluationRepository(session), bot, settings)

    await run_periodically("Evaluation polls", batch, settings.interval_seconds, once)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.once))


if __name__ == "__main__":
    main()
