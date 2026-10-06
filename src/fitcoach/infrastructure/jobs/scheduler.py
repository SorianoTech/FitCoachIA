"""In-app scheduler: claims due jobs from ``job_execution`` and dispatches them by type."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telegram import Bot
from telegram.error import TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.retry_policy import RetryPolicy
from fitcoach.domain.scheduled_job import ClaimedJob, JobOutcome, JobType
from fitcoach.domain.training_evaluation import is_superseded
from fitcoach.domain.training_lifecycle import utc_now
from fitcoach.infrastructure.config.settings import (
    EvaluationSettings,
    SchedulerSettings,
    TrainingSettings,
)
from fitcoach.infrastructure.database.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from fitcoach.infrastructure.database.postgres_job_repository import PostgresJobRepository
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.jobs.telegram_delivery import classify_failure
from fitcoach.repository.evaluation_repository import PollTarget, SentPoll
from fitcoach.repository.job_repository import JobConflictError

logger = logging.getLogger(__name__)

Handler = Callable[[ClaimedJob, AsyncSession, RetryPolicy], Awaitable[JobOutcome]]


@dataclass(frozen=True)
class _JobRunner:
    handler: Handler
    policy: RetryPolicy


def poll_question(week: int, goal: str | None) -> str:
    label = Constants.TRAINING_GOAL_LABELS.get(goal or "")
    if label is None:
        return Constants.EVALUATION_POLL_QUESTION_NO_GOAL.format(week=week)
    return Constants.EVALUATION_POLL_QUESTION.format(week=week, goal=label.lower())


class JobScheduler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot,
        settings: SchedulerSettings,
        training: TrainingSettings,
        evaluation: EvaluationSettings,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._bot = bot
        self._interval = settings.interval_seconds
        self._clock = clock
        self._stop = asyncio.Event()
        self._runners: dict[JobType, _JobRunner] = {
            JobType.TRAINING_REMINDER: _JobRunner(
                self._run_training_reminder, training.to_retry_policy()
            ),
            JobType.EVALUATION_POLL: _JobRunner(
                self._run_evaluation_poll, evaluation.to_retry_policy()
            ),
        }

    async def run(self, stop: asyncio.Event) -> None:
        self._stop = stop
        logger.info(
            "Scheduler started: interval=%ss types=%s",
            self._interval,
            sorted(self._runners),
        )
        while not stop.is_set():
            try:
                await self.tick()
            except SQLAlchemyError:
                logger.exception("Scheduler database/schema unavailable")
            except Exception:
                logger.exception("Scheduler tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._interval)
            except TimeoutError:
                continue
        logger.info("Scheduler stopped")

    async def tick(self) -> int:
        """Run every due job in one session; returns how many were claimed."""
        processed = 0
        async with self._session_factory() as session:
            jobs = PostgresJobRepository(session)
            for job_type, runner in self._runners.items():
                processed += await self._drain(session, jobs, job_type, runner)
        logger.info("Scheduler tick finished: processed=%s", processed)
        return processed

    async def _drain(
        self,
        session: AsyncSession,
        jobs: PostgresJobRepository,
        job_type: JobType,
        runner: _JobRunner,
    ) -> int:
        processed = 0
        while processed < runner.policy.batch_size and not self._stop.is_set():
            job = await jobs.claim(self._clock(), runner.policy.sending_timeout, (job_type,))
            if job is None:
                break
            processed += 1
            outcome = await self._execute(job, session, runner)
            try:
                await jobs.finish(job, outcome, self._clock())
            except JobConflictError:
                logger.exception(
                    "Job %s (%s) ran but its lease expired; its result was not recorded",
                    job.id,
                    job.job_type,
                )
        return processed

    async def _execute(
        self, job: ClaimedJob, session: AsyncSession, runner: _JobRunner
    ) -> JobOutcome:
        if job.attempts > runner.policy.max_attempts:
            logger.error(
                "Job %s (%s) exhausted attempts after an interruption", job.id, job.job_type
            )
            return JobOutcome.failed()
        try:
            return await runner.handler(job, session, runner.policy)
        except SQLAlchemyError:
            raise
        except Exception:
            logger.exception("Job %s (%s) crashed", job.id, job.job_type)
            await session.rollback()
            return JobOutcome.failed()

    def _failure(self, job: ClaimedJob, error: TelegramError, policy: RetryPolicy) -> JobOutcome:
        outcome = classify_failure(error, job.attempts, policy, self._clock())
        logger.log(
            logging.ERROR if outcome.failed else logging.WARNING,
            "Job %s (%s) not delivered to chat %s: retry_at=%s failed=%s unexpected=%s",
            job.id,
            job.job_type,
            job.chat_id,
            outcome.retry_at,
            outcome.failed,
            outcome.unexpected,
            exc_info=True,
        )
        if outcome.failed or outcome.retry_at is None:
            return JobOutcome.failed()
        return JobOutcome.retry(outcome.retry_at)

    async def _run_training_reminder(
        self, job: ClaimedJob, session: AsyncSession, policy: RetryPolicy
    ) -> JobOutcome:
        now = self._clock()
        target = await PostgresTrainingRepository(session).reminder_target(
            job.chat_id, int(str(job.payload["mesocycle_id"])), now
        )
        if target is None:
            return JobOutcome.cancelled()
        try:
            await self._bot.send_message(
                chat_id=job.chat_id,
                message_thread_id=target.thread_id,
                text=Constants.TRAINING_DUE_MESSAGE,
            )
        except TelegramError as error:
            return self._failure(job, error, policy)
        return JobOutcome.done()

    async def _run_evaluation_poll(
        self, job: ClaimedJob, session: AsyncSession, policy: RetryPolicy
    ) -> JobOutcome:
        now = self._clock()
        week = int(str(job.payload["week_number"]))
        evaluations = PostgresEvaluationRepository(session)
        target = await evaluations.open_current_plan(int(str(job.payload["mesocycle_id"])))
        if target is None or is_superseded(target.started_at, week, now):
            return JobOutcome.cancelled()
        await self._close_previous(job, await evaluations.previous_unanswered(job.chat_id))
        try:
            message = await self._bot.send_poll(
                chat_id=job.chat_id,
                message_thread_id=target.thread_id,
                question=poll_question(week, target.goal),
                options=Constants.EVALUATION_POLL_OPTIONS,
                is_anonymous=False,
                allows_multiple_answers=False,
                allows_revoting=False,
            )
        except TelegramError as error:
            return self._failure(job, error, policy)
        if message.poll is None:
            logger.error("Job %s: Telegram answered without a poll", job.id)
            return JobOutcome.failed()
        # Flushed here and committed by the scheduler together with the job's final state.
        await evaluations.save_sent(
            self._sent(job, target, week, message.poll.id, message.message_id)
        )
        return JobOutcome.done()

    def _sent(
        self, job: ClaimedJob, target: PollTarget, week: int, poll_id: str, message_id: int
    ) -> SentPoll:
        return SentPoll(
            job_id=job.id,
            chat_id=job.chat_id,
            target=target,
            week_number=week,
            poll_id=poll_id,
            message_id=message_id,
            sent_at=self._clock(),
        )

    async def _close_previous(self, job: ClaimedJob, message_ids: list[int]) -> None:
        # Best effort: failing to close an old poll must not block the new one.
        for message_id in message_ids:
            try:
                await self._bot.stop_poll(chat_id=job.chat_id, message_id=message_id)
            except TelegramError:
                logger.warning(
                    "Job %s could not close previous poll message %s",
                    job.id,
                    message_id,
                    exc_info=True,
                )
