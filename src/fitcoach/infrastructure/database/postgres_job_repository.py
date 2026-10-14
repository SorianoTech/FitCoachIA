from collections.abc import Collection
from datetime import datetime, timedelta
from typing import cast

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.scheduled_job import (
    ClaimedJob,
    JobOutcome,
    JobState,
    JobType,
    evaluation_poll_key,
    training_reminder_key,
)
from fitcoach.domain.training_evaluation import upcoming_polls
from fitcoach.infrastructure.database.models import JobExecutionRecord, TrainingMesocycleRecord
from fitcoach.repository.job_repository import JobConflictError

_CLAIMABLE = (JobState.PENDING, JobState.RUNNING)
_FINAL = (JobState.DONE, JobState.FAILED, JobState.CANCELLED)


def cycle_jobs(mesocycle_id: int) -> ColumnElement[bool]:
    return cast(
        "ColumnElement[bool]",
        JobExecutionRecord.payload["mesocycle_id"].as_integer() == mesocycle_id,
    )


async def schedule_job(
    session: AsyncSession,
    job_type: JobType,
    chat_id: int,
    payload: dict[str, object],
    dedup_key: str,
    execution_date: datetime,
) -> None:
    """Register a job inside the caller's transaction; a repeated ``dedup_key`` is ignored."""
    await session.execute(
        insert(JobExecutionRecord)
        .values(
            job_type=job_type,
            chat_id=chat_id,
            payload=payload,
            dedup_key=dedup_key,
            execution_date=execution_date,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
    )


async def schedule_training_reminder(
    session: AsyncSession, cycle: TrainingMesocycleRecord, occasion: int, execution_date: datetime
) -> None:
    await schedule_job(
        session,
        JobType.TRAINING_REMINDER,
        cycle.chat_id,
        {"mesocycle_id": cycle.id},
        training_reminder_key(cycle.id, occasion),
        execution_date,
    )


def _cycle_reminders(cycle: TrainingMesocycleRecord) -> tuple[ColumnElement[bool], ...]:
    return (JobExecutionRecord.job_type == JobType.TRAINING_REMINDER, cycle_jobs(cycle.id))


async def _next_reminder_occasion(session: AsyncSession, cycle: TrainingMesocycleRecord) -> int:
    count = await session.scalar(
        select(func.count(JobExecutionRecord.id)).where(*_cycle_reminders(cycle))
    )
    return count or 0


async def reschedule_training_reminder(
    session: AsyncSession, cycle: TrainingMesocycleRecord, execution_date: datetime
) -> None:
    """Replace the pending reminder of a cycle by a new one (postpone)."""
    await cancel_pending_jobs(session, *_cycle_reminders(cycle))
    await schedule_training_reminder(
        session, cycle, await _next_reminder_occasion(session, cycle), execution_date
    )


async def ensure_training_reminder(session: AsyncSession, cycle: TrainingMesocycleRecord) -> None:
    """Re-register the reminder unless the latest one is still queued or already delivered."""
    if cycle.expected_end_at is None or cycle.completed_at is not None:
        return
    latest = await session.scalar(
        select(JobExecutionRecord.state)
        .where(*_cycle_reminders(cycle))
        .order_by(JobExecutionRecord.created_at.desc(), JobExecutionRecord.execution_date.desc())
        .limit(1)
    )
    if latest in (JobState.PENDING, JobState.RUNNING, JobState.DONE):
        return
    await schedule_training_reminder(
        session, cycle, await _next_reminder_occasion(session, cycle), cycle.expected_end_at
    )


async def schedule_cycle_jobs(
    session: AsyncSession, cycle: TrainingMesocycleRecord, now: datetime
) -> None:
    """Register the future polls and the end-of-cycle reminder of a dated cycle."""
    if cycle.started_at is None:
        return
    for week, due in upcoming_polls(cycle.started_at, now):
        await schedule_job(
            session,
            JobType.EVALUATION_POLL,
            cycle.chat_id,
            {"mesocycle_id": cycle.id, "week_number": week},
            evaluation_poll_key(cycle.id, week),
            due,
        )
    if cycle.expected_end_at is not None:
        await schedule_training_reminder(session, cycle, 0, cycle.expected_end_at)


async def cancel_pending_jobs(session: AsyncSession, *criteria: ColumnElement[bool]) -> None:
    """Drop jobs not yet claimed; one already running finishes and stays recorded."""
    await session.execute(
        update(JobExecutionRecord)
        .where(JobExecutionRecord.state == JobState.PENDING, *criteria)
        .values(state=JobState.CANCELLED)
    )


class PostgresJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(
        self, now: datetime, lock_timeout: timedelta, types: Collection[JobType]
    ) -> ClaimedJob | None:
        if not types:
            return None
        record = await self._session.scalar(
            select(JobExecutionRecord)
            .where(
                JobExecutionRecord.job_type.in_(types),
                JobExecutionRecord.state.in_(_CLAIMABLE),
                JobExecutionRecord.execution_date <= now,
                JobExecutionRecord.locked_until.is_(None)
                | (JobExecutionRecord.locked_until <= now),
            )
            .order_by(JobExecutionRecord.execution_date, JobExecutionRecord.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if record is None:
            await self._session.commit()
            return None
        record.state = JobState.RUNNING
        record.locked_until = now + lock_timeout
        record.attempts += 1
        job = ClaimedJob(
            id=record.id,
            job_type=JobType(record.job_type),
            chat_id=record.chat_id,
            payload=dict(record.payload),
            attempts=record.attempts,
            execution_date=record.execution_date,
        )
        await self._session.commit()
        return job

    async def finish(self, job: ClaimedJob, outcome: JobOutcome, now: datetime) -> None:
        record = await self._session.scalar(
            select(JobExecutionRecord).where(JobExecutionRecord.id == job.id).with_for_update()
        )
        if record is None or record.state != JobState.RUNNING or record.attempts != job.attempts:
            await self._session.rollback()
            raise JobConflictError(f"Job {job.id} is no longer locked")
        record.state = outcome.state
        record.locked_until = None
        if outcome.retry_at is not None:
            record.execution_date = outcome.retry_at
        if outcome.state in _FINAL:
            record.executed_at = now
        await self._session.commit()
