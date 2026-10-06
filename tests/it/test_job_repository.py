import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.scheduled_job import (
    ClaimedJob,
    JobOutcome,
    JobState,
    JobType,
    evaluation_poll_key,
)
from fitcoach.infrastructure.database.models import JobExecutionRecord, TrainingMesocycleRecord
from fitcoach.infrastructure.database.postgres_job_repository import (
    PostgresJobRepository,
    cancel_pending_jobs,
    cycle_jobs,
    schedule_cycle_jobs,
    schedule_job,
    schedule_training_reminder,
)
from fitcoach.repository.job_repository import JobConflictError

CHAT_ID = 882378
OTHER_CHAT_ID = 882379
LOCK = timedelta(minutes=2)
ALL_TYPES = tuple(JobType)


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    ).replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def clean() -> None:
        async with sessions() as session:
            chats = (CHAT_ID, OTHER_CHAT_ID)
            await session.execute(
                delete(JobExecutionRecord).where(JobExecutionRecord.chat_id.in_(chats))
            )
            await session.execute(
                delete(TrainingMesocycleRecord).where(TrainingMesocycleRecord.chat_id.in_(chats))
            )
            await session.commit()

    await clean()
    try:
        yield sessions
    finally:
        await clean()
        await engine.dispose()


async def _add_job(
    factory: async_sessionmaker[AsyncSession],
    key: str,
    due: datetime,
    job_type: JobType = JobType.EVALUATION_POLL,
    chat_id: int = CHAT_ID,
    payload: dict[str, object] | None = None,
) -> None:
    async with factory() as session:
        await schedule_job(session, job_type, chat_id, payload or {}, key, due)
        await session.commit()


async def _jobs(factory: async_sessionmaker[AsyncSession]) -> list[JobExecutionRecord]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(JobExecutionRecord)
                .where(JobExecutionRecord.chat_id.in_((CHAT_ID, OTHER_CHAT_ID)))
                .order_by(JobExecutionRecord.dedup_key)
            )
        )


async def _claim(
    factory: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
    types: tuple[JobType, ...] = ALL_TYPES,
) -> ClaimedJob | None:
    async with factory() as session:
        return await PostgresJobRepository(session).claim(now or datetime.now(UTC), LOCK, types)


async def _finish(
    factory: async_sessionmaker[AsyncSession],
    job: ClaimedJob,
    outcome: JobOutcome,
    now: datetime | None = None,
) -> None:
    async with factory() as session:
        await PostgresJobRepository(session).finish(job, outcome, now or datetime.now(UTC))


async def _new_cycle(
    factory: async_sessionmaker[AsyncSession],
    chat_id: int = CHAT_ID,
    started_at: datetime | None = None,
) -> TrainingMesocycleRecord:
    cycle = TrainingMesocycleRecord(
        chat_id=chat_id,
        started_at=started_at,
        expected_end_at=None if started_at is None else started_at + timedelta(days=28),
    )
    async with factory() as session:
        session.add(cycle)
        await session.commit()
    return cycle


@pytest.mark.asyncio
async def test_schedule_job_ignores_a_repeated_dedup_key(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    due = datetime.now(UTC)
    await _add_job(factory, "k1", due)
    await _add_job(factory, "k1", due + timedelta(days=1))

    jobs = await _jobs(factory)

    assert [(job.dedup_key, job.execution_date) for job in jobs] == [("k1", due)]


@pytest.mark.asyncio
async def test_schedule_cycle_jobs_registers_four_polls_and_one_reminder(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    cycle = await _new_cycle(factory, started_at=now)

    for _ in range(2):
        async with factory() as session:
            await schedule_cycle_jobs(session, cycle, now)
            await session.commit()

    jobs = await _jobs(factory)
    assert sorted(job.job_type for job in jobs) == ["evaluation_poll"] * 4 + ["training_reminder"]
    reminder = next(job for job in jobs if job.job_type == JobType.TRAINING_REMINDER)
    assert reminder.execution_date == cycle.expected_end_at
    assert reminder.payload == {"mesocycle_id": cycle.id}
    assert sorted(
        job.execution_date for job in jobs if job.job_type == JobType.EVALUATION_POLL
    ) == [now + timedelta(weeks=week) for week in range(1, 5)]


@pytest.mark.asyncio
async def test_schedule_cycle_jobs_skips_past_polls(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    cycle = await _new_cycle(factory, started_at=now - timedelta(days=10))

    async with factory() as session:
        await schedule_cycle_jobs(session, cycle, now)
        await session.commit()

    keys = [job.dedup_key for job in await _jobs(factory) if job.job_type == "evaluation_poll"]
    assert keys == [evaluation_poll_key(cycle.id, week) for week in (2, 3, 4)]


@pytest.mark.asyncio
async def test_schedule_cycle_jobs_ignores_an_undated_cycle(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    cycle = await _new_cycle(factory)

    async with factory() as session:
        await schedule_cycle_jobs(session, cycle, datetime.now(UTC))
        await session.commit()

    assert await _jobs(factory) == []


@pytest.mark.asyncio
async def test_claim_leases_a_due_job_and_counts_the_attempt(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1), payload={"a": 1})

    job = await _claim(factory)

    assert job is not None
    assert (job.job_type, job.chat_id, job.payload, job.attempts) == (
        JobType.EVALUATION_POLL,
        CHAT_ID,
        {"a": 1},
        1,
    )
    record = (await _jobs(factory))[0]
    assert record.state == JobState.RUNNING
    assert record.locked_until is not None


@pytest.mark.asyncio
async def test_claim_ignores_future_jobs_and_inactive_types(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _add_job(factory, "future", now + timedelta(hours=1))
    await _add_job(factory, "reminder", now - timedelta(minutes=1), JobType.TRAINING_REMINDER)

    assert await _claim(factory, types=(JobType.EVALUATION_POLL,)) is None
    assert await _claim(factory, types=()) is None
    assert all(job.state == JobState.PENDING for job in await _jobs(factory))


@pytest.mark.asyncio
async def test_claim_serves_the_oldest_due_job_first(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _add_job(factory, "late", now - timedelta(minutes=1))
    await _add_job(factory, "early", now - timedelta(hours=1))

    first = await _claim(factory)
    second = await _claim(factory)

    assert first is not None
    assert second is not None
    assert (first.execution_date < second.execution_date) is True


@pytest.mark.asyncio
async def test_claim_does_not_hand_out_a_locked_job_twice(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1))

    claims = await asyncio.gather(_claim(factory), _claim(factory))

    assert [claim is not None for claim in claims].count(True) == 1


@pytest.mark.asyncio
async def test_claim_recovers_a_job_whose_lease_expired(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _add_job(factory, "k1", now - timedelta(minutes=1))
    first = await _claim(factory, now)

    assert await _claim(factory, now + timedelta(seconds=30)) is None
    second = await _claim(factory, now + LOCK + timedelta(seconds=1))

    assert first is not None
    assert second is not None
    assert (first.id, second.attempts) == (second.id, 2)


@pytest.mark.asyncio
async def test_finish_done_records_the_execution_date(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1))
    job = await _claim(factory)
    assert job is not None
    finished_at = datetime.now(UTC)

    await _finish(factory, job, JobOutcome.done(), finished_at)

    record = (await _jobs(factory))[0]
    assert (record.state, record.executed_at, record.locked_until) == (
        JobState.DONE,
        finished_at,
        None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "state"),
    [(JobOutcome.failed(), JobState.FAILED), (JobOutcome.cancelled(), JobState.CANCELLED)],
    ids=["failed", "cancelled"],
)
async def test_finish_failed_and_cancelled_are_final(
    factory: async_sessionmaker[AsyncSession], outcome: JobOutcome, state: JobState
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1))
    job = await _claim(factory)
    assert job is not None

    await _finish(factory, job, outcome)

    record = (await _jobs(factory))[0]
    assert (record.state, record.executed_at is not None) == (state, True)
    assert await _claim(factory) is None


@pytest.mark.asyncio
async def test_finish_retry_reschedules_without_executed_at(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1))
    job = await _claim(factory)
    assert job is not None
    retry_at = datetime.now(UTC) + timedelta(minutes=5)

    await _finish(factory, job, JobOutcome.retry(retry_at))

    record = (await _jobs(factory))[0]
    assert (record.state, record.execution_date, record.executed_at, record.attempts) == (
        JobState.PENDING,
        retry_at,
        None,
        1,
    )


@pytest.mark.asyncio
async def test_finish_raises_conflict_when_another_scheduler_reclaimed_the_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _add_job(factory, "k1", now - timedelta(minutes=1))
    stale = await _claim(factory, now)
    assert stale is not None
    assert await _claim(factory, now + LOCK + timedelta(seconds=1)) is not None

    with pytest.raises(JobConflictError):
        await _finish(factory, stale, JobOutcome.done())

    assert (await _jobs(factory))[0].state == JobState.RUNNING


@pytest.mark.asyncio
async def test_finish_raises_conflict_when_the_job_already_finished(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _add_job(factory, "k1", datetime.now(UTC) - timedelta(minutes=1))
    job = await _claim(factory)
    assert job is not None
    await _finish(factory, job, JobOutcome.done())

    with pytest.raises(JobConflictError):
        await _finish(factory, job, JobOutcome.failed())

    assert (await _jobs(factory))[0].state == JobState.DONE


@pytest.mark.asyncio
async def test_cancel_pending_jobs_only_touches_matching_pending_jobs(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    due = datetime.now(UTC) - timedelta(minutes=1)
    await _add_job(factory, "a", due - timedelta(hours=1), payload={"mesocycle_id": 1})
    await _add_job(factory, "b", due, payload={"mesocycle_id": 2})
    await _add_job(factory, "c", due, chat_id=OTHER_CHAT_ID, payload={"mesocycle_id": 1})
    running = await _claim(factory, types=(JobType.EVALUATION_POLL,))
    assert running is not None

    async with factory() as session:
        await cancel_pending_jobs(session, cycle_jobs(1), JobExecutionRecord.chat_id == CHAT_ID)
        await session.commit()

    states = {job.dedup_key: job.state for job in await _jobs(factory)}
    assert states["a"] == JobState.RUNNING
    assert states["b"] == JobState.PENDING
    assert states["c"] == JobState.PENDING


@pytest.mark.asyncio
async def test_cancel_pending_jobs_by_chat_and_cycle(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    due = datetime.now(UTC) + timedelta(days=1)
    await _add_job(factory, "a", due, payload={"mesocycle_id": 1})
    await _add_job(factory, "b", due, payload={"mesocycle_id": 2})
    await _add_job(factory, "c", due, chat_id=OTHER_CHAT_ID, payload={"mesocycle_id": 1})

    async with factory() as session:
        await cancel_pending_jobs(session, cycle_jobs(1), JobExecutionRecord.chat_id == CHAT_ID)
        await session.commit()

    states = {job.dedup_key: job.state for job in await _jobs(factory)}
    assert states == {"a": "cancelled", "b": "pending", "c": "pending"}


@pytest.mark.asyncio
async def test_a_new_reminder_occasion_does_not_collide_with_the_first(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    cycle = await _new_cycle(factory, started_at=now)

    async with factory() as session:
        await schedule_training_reminder(session, cycle, 0, now)
        await schedule_training_reminder(session, cycle, 1, now + timedelta(days=3))
        await session.commit()

    assert len(await _jobs(factory)) == 2
