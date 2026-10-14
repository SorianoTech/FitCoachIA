import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.scheduled_job import JobState, JobType, training_reminder_key
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.database.models import (
    JobExecutionRecord,
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.repository.training_repository import TrainingConflictError
from tests.unit_test.conftest import build_plan_payload

CHAT_ID = 882380


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
            await PostgresConversationRepository(session).restart_interview(CHAT_ID)
            await session.execute(
                delete(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
            )
            await session.execute(
                delete(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
            )
            await session.execute(
                delete(TrainingMesocycleRecord).where(TrainingMesocycleRecord.chat_id == CHAT_ID)
            )
            await session.commit()

    await clean()
    async with sessions() as session:
        await PostgresConversationRepository(session).save_training_plan(
            CHAT_ID,
            TrainingPlan.model_validate(build_plan_payload()),
            "initial",
            "train",
            "ok",
            None,
        )
    try:
        yield sessions
    finally:
        await clean()
        await engine.dispose()


async def _jobs(
    factory: async_sessionmaker[AsyncSession], job_type: JobType | None = None
) -> list[JobExecutionRecord]:
    statement = select(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
    if job_type is not None:
        statement = statement.where(JobExecutionRecord.job_type == job_type)
    async with factory() as session:
        return list(
            await session.scalars(
                statement.order_by(JobExecutionRecord.created_at, JobExecutionRecord.dedup_key)
            )
        )


async def _states(
    factory: async_sessionmaker[AsyncSession], job_type: JobType | None = None
) -> list[str]:
    return sorted(job.state for job in await _jobs(factory, job_type))


async def _cycle_id(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        cycle = await PostgresTrainingRepository(session).get_cycle(CHAT_ID)
    assert cycle is not None
    return cycle.id


async def _set_reminder_states(factory: async_sessionmaker[AsyncSession], state: str) -> None:
    async with factory() as session:
        await session.execute(
            update(JobExecutionRecord)
            .where(
                JobExecutionRecord.chat_id == CHAT_ID,
                JobExecutionRecord.job_type == JobType.TRAINING_REMINDER,
            )
            .values(state=state)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_a_new_plan_registers_four_polls_and_one_reminder(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    cycle_id = await _cycle_id(factory)

    jobs = await _jobs(factory)

    assert sorted(job.job_type for job in jobs) == ["evaluation_poll"] * 4 + ["training_reminder"]
    assert {job.payload["mesocycle_id"] for job in jobs} == {cycle_id}
    assert {job.state for job in jobs} == {"pending"}


@pytest.mark.asyncio
async def test_closing_the_cycle_cancels_its_pending_jobs(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        await PostgresTrainingRepository(session).close_cycle(CHAT_ID, datetime.now(UTC))

    assert set(await _states(factory)) == {"cancelled"}


@pytest.mark.asyncio
async def test_a_renewal_registers_the_jobs_of_the_new_cycle_only(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    old_cycle = await _cycle_id(factory)
    start = datetime.now(UTC) + timedelta(days=1)
    async with factory() as session:
        training = PostgresTrainingRepository(session)
        current = await PostgresConversationRepository(session).get_current_plan(CHAT_ID)
        assert current is not None
        flow = await training.start(CHAT_ID, "renewal")
        flow.draft = current.plan
        flow.report = "renewal"
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)
        await training.close_cycle(CHAT_ID, datetime.now(UTC))
        await training.accept(CHAT_ID, flow.id, start)

    new_cycle = await _cycle_id(factory)
    jobs = await _jobs(factory)
    by_cycle = {
        cycle: sorted(job.state for job in jobs if job.payload["mesocycle_id"] == cycle)
        for cycle in (old_cycle, new_cycle)
    }
    assert new_cycle != old_cycle
    assert by_cycle[old_cycle] == ["cancelled"] * 5
    assert by_cycle[new_cycle] == ["pending"] * 5
    first_poll = min(
        job.execution_date
        for job in jobs
        if job.payload["mesocycle_id"] == new_cycle and job.job_type == JobType.EVALUATION_POLL
    )
    assert first_poll == start + timedelta(weeks=1)


@pytest.mark.asyncio
async def test_a_failed_renewal_registers_nothing(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        training = PostgresTrainingRepository(session)
        current = await PostgresConversationRepository(session).get_current_plan(CHAT_ID)
        assert current is not None
        flow = await training.start(CHAT_ID, "renewal")
        flow.draft = current.plan
        flow.report = "renewal"
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)
        with pytest.raises(TrainingConflictError, match="complete"):
            await training.accept(CHAT_ID, flow.id, datetime.now(UTC))

    assert len(await _jobs(factory)) == 5


@pytest.mark.asyncio
async def test_restarting_the_interview_cancels_pending_jobs_but_keeps_finished_ones(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        await session.execute(
            update(JobExecutionRecord)
            .where(
                JobExecutionRecord.chat_id == CHAT_ID,
                JobExecutionRecord.job_type == JobType.TRAINING_REMINDER,
            )
            .values(state=JobState.DONE)
        )
        await session.commit()

    async with factory() as session:
        await PostgresConversationRepository(session).restart_interview(CHAT_ID)

    assert await _states(factory, JobType.EVALUATION_POLL) == ["cancelled"] * 4
    assert await _states(factory, JobType.TRAINING_REMINDER) == ["done"]


@pytest.mark.asyncio
async def test_postponing_replaces_the_pending_reminder_and_keeps_the_polls(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    cycle_id = await _cycle_id(factory)
    until = datetime.now(UTC) + timedelta(days=40)

    for _ in range(2):
        async with factory() as session:
            await PostgresTrainingRepository(session).postpone(CHAT_ID, until)
            until += timedelta(days=1)

    reminders = {job.dedup_key: job for job in await _jobs(factory, JobType.TRAINING_REMINDER)}
    assert {key: job.state for key, job in reminders.items()} == {
        training_reminder_key(cycle_id, 0): "cancelled",
        training_reminder_key(cycle_id, 1): "cancelled",
        training_reminder_key(cycle_id, 2): "pending",
    }
    assert reminders[training_reminder_key(cycle_id, 2)].execution_date == until - timedelta(days=1)
    assert await _states(factory, JobType.EVALUATION_POLL) == ["pending"] * 4


@pytest.mark.asyncio
async def test_postponing_a_closed_cycle_changes_no_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        await PostgresTrainingRepository(session).close_cycle(CHAT_ID, datetime.now(UTC))
    before = [(job.dedup_key, job.state) for job in await _jobs(factory)]

    async with factory() as session:
        with pytest.raises(TrainingConflictError, match="closed"):
            await PostgresTrainingRepository(session).postpone(
                CHAT_ID, datetime.now(UTC) + timedelta(days=3)
            )

    assert [(job.dedup_key, job.state) for job in await _jobs(factory)] == before


@pytest.mark.asyncio
async def test_enabling_reminders_registers_one_only_when_none_is_queued_or_delivered(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def enable() -> None:
        async with factory() as session:
            await PostgresTrainingRepository(session).set_reminders(CHAT_ID, True)

    await enable()
    assert await _states(factory, JobType.TRAINING_REMINDER) == ["pending"]

    await _set_reminder_states(factory, JobState.DONE)
    await enable()
    assert await _states(factory, JobType.TRAINING_REMINDER) == ["done"]

    await _set_reminder_states(factory, JobState.CANCELLED)
    await enable()
    assert await _states(factory, JobType.TRAINING_REMINDER) == ["cancelled", "pending"]


@pytest.mark.asyncio
async def test_disabling_reminders_registers_nothing(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _set_reminder_states(factory, JobState.CANCELLED)

    async with factory() as session:
        await PostgresTrainingRepository(session).set_reminders(CHAT_ID, False)

    assert await _states(factory, JobType.TRAINING_REMINDER) == ["cancelled"]


@pytest.mark.asyncio
async def test_enabling_reminders_on_a_closed_cycle_registers_nothing(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        training = PostgresTrainingRepository(session)
        await training.close_cycle(CHAT_ID, datetime.now(UTC))
        await training.set_reminders(CHAT_ID, True)

    assert await _states(factory, JobType.TRAINING_REMINDER) == ["cancelled"]


@pytest.mark.asyncio
async def test_dating_a_legacy_cycle_registers_its_jobs(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    cycle_id = await _cycle_id(factory)
    async with factory() as session:
        await session.execute(
            delete(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
        )
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.id == cycle_id)
            .values(started_at=None, expected_end_at=None)
        )
        await session.commit()
    start = datetime.now(UTC)

    async with factory() as session:
        await PostgresTrainingRepository(session).set_start(CHAT_ID, start)

    jobs = await _jobs(factory)
    assert sorted(job.job_type for job in jobs) == ["evaluation_poll"] * 4 + ["training_reminder"]
    assert {job.payload["mesocycle_id"] for job in jobs} == {cycle_id}


@pytest.mark.asyncio
async def test_dating_an_already_dated_cycle_is_rejected_without_new_jobs(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        with pytest.raises(TrainingConflictError, match="undated"):
            await PostgresTrainingRepository(session).set_start(CHAT_ID, datetime.now(UTC))

    assert len(await _jobs(factory)) == 5
