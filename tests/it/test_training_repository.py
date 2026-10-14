import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.scheduled_job import JobType
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.database.models import (
    JobExecutionRecord,
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
    TrainingPlanRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.repository.training_repository import (
    ReminderDelivery,
    ReminderTarget,
    TrainingConflictError,
)
from tests.unit_test.conftest import build_plan_payload

CHAT_ID = 882299


@pytest_asyncio.fixture
async def training_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    ).replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        conversation = PostgresConversationRepository(session)
        await conversation.restart_interview(CHAT_ID)
        await conversation.save_training_plan(
            CHAT_ID,
            TrainingPlan.model_validate(build_plan_payload()),
            "initial",
            "train",
            "ok",
            None,
        )
    try:
        yield factory
    finally:
        async with factory() as session:
            await PostgresConversationRepository(session).restart_interview(CHAT_ID)
            await session.execute(
                delete(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
            )
            await session.execute(
                delete(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
            )
            await session.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_two_confirmations_create_exactly_one_version(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        conversation = PostgresConversationRepository(session)
        flow = await training.start(CHAT_ID, "exercise_swap")
        flow.draft = (await conversation.get_current_plan(CHAT_ID)).plan
        flow.report = "swap"
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)

    async def accept() -> int:
        async with training_factory() as session:
            return await PostgresTrainingRepository(session).accept(
                CHAT_ID, flow.id, datetime.now(UTC)
            )

    ids = await asyncio.gather(accept(), accept())
    assert ids[0] == ids[1]
    async with training_factory() as session:
        rows = list(
            await session.scalars(
                select(TrainingPlanRecord.version).where(TrainingPlanRecord.chat_id == CHAT_ID)
            )
        )
        assert sorted(rows) == [1, 2]


@pytest.mark.asyncio
async def test_generation_claim_is_exclusive_and_cancel_rejects_late_result(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        flow = await training.start(CHAT_ID, "renewal")

    async def claim() -> object:
        async with training_factory() as session:
            try:
                return await PostgresTrainingRepository(session).claim_generation(CHAT_ID, flow.id)
            except TrainingConflictError as error:
                await session.rollback()
                return error

    claims = await asyncio.gather(claim(), claim())
    assert sum(isinstance(item, TrainingConflictError) for item in claims) == 1
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        generation = await training.get_workflow(CHAT_ID)
        await training.cancel(CHAT_ID)
        generation.state = "awaiting_confirmation"
        with pytest.raises(TrainingConflictError, match="concurrently"):
            await training.save(CHAT_ID, generation)


async def _reminder_jobs(
    factory: async_sessionmaker[AsyncSession],
) -> list[JobExecutionRecord]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(JobExecutionRecord)
                .where(
                    JobExecutionRecord.chat_id == CHAT_ID,
                    JobExecutionRecord.job_type == JobType.TRAINING_REMINDER,
                )
                .order_by(JobExecutionRecord.dedup_key)
            )
        )


async def _reserve(
    factory: async_sessionmaker[AsyncSession], now: datetime, thread_id: int | None = 22
) -> ReminderDelivery | None:
    async with factory() as session:
        return await PostgresTrainingRepository(session).reserve_interaction_reminder(
            CHAT_ID, thread_id, now
        )


async def _postpone_to(factory: async_sessionmaker[AsyncSession], until: datetime) -> None:
    async with factory() as session:
        await PostgresTrainingRepository(session).postpone(CHAT_ID, until)


@pytest.mark.asyncio
async def test_postponing_before_first_reminder_does_not_double_notify(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))

    delivery = await _reserve(training_factory, now)
    assert delivery is not None
    assert delivery.chat_id == CHAT_ID
    async with training_factory() as session:
        await PostgresTrainingRepository(session).finish_reminder(delivery)

    assert await _reserve(training_factory, now) is None
    assert [job.state for job in await _reminder_jobs(training_factory)] == ["cancelled", "done"]


@pytest.mark.asyncio
async def test_reserved_reminder_stays_locked_for_two_minutes(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))

    delivery = await _reserve(training_factory, now)

    assert delivery is not None
    assert delivery.thread_id == 22
    [_, job] = await _reminder_jobs(training_factory)
    assert (job.state, job.locked_until) == ("running", now + timedelta(minutes=2))
    # Locked before the lease expires, claimable again afterwards.
    assert await _reserve(training_factory, now + timedelta(minutes=1)) is None
    again = await _reserve(training_factory, now + timedelta(minutes=3))
    assert again is not None
    assert (again.id, again.attempts) == (delivery.id, 2)


@pytest.mark.asyncio
async def test_nothing_is_reserved_before_the_cycle_is_due(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _reserve(training_factory, datetime.now(UTC)) is None

    assert [job.state for job in await _reminder_jobs(training_factory)] == ["pending"]


@pytest.mark.asyncio
@pytest.mark.parametrize("blocker", ["disabled", "closed", "open_workflow"])
async def test_nothing_is_reserved_when_the_reminder_does_not_apply(
    training_factory: async_sessionmaker[AsyncSession], blocker: str
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        if blocker == "disabled":
            await training.set_reminders(CHAT_ID, False)
        elif blocker == "closed":
            await training.close_cycle(CHAT_ID, now)
        else:
            await training.start(CHAT_ID, "renewal")

    assert await _reserve(training_factory, now) is None


@pytest.mark.asyncio
async def test_finishing_with_a_retry_reschedules_the_reminder(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))
    delivery = await _reserve(training_factory, now)
    assert delivery is not None
    retry_at = now + timedelta(minutes=5)

    async with training_factory() as session:
        await PostgresTrainingRepository(session).finish_reminder(delivery, retry_at=retry_at)

    [_, job] = await _reminder_jobs(training_factory)
    assert (job.state, job.execution_date, job.locked_until) == ("pending", retry_at, None)
    assert await _reserve(training_factory, now) is None


@pytest.mark.asyncio
async def test_finishing_as_failed_is_final(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))
    delivery = await _reserve(training_factory, now)
    assert delivery is not None

    async with training_factory() as session:
        await PostgresTrainingRepository(session).finish_reminder(delivery, failed=True)

    assert [job.state for job in await _reminder_jobs(training_factory)] == ["cancelled", "failed"]
    assert await _reserve(training_factory, now + timedelta(hours=1)) is None


@pytest.mark.asyncio
async def test_a_reservation_whose_lease_was_taken_cannot_be_finished(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))
    stale = await _reserve(training_factory, now)
    assert stale is not None
    assert await _reserve(training_factory, now + timedelta(minutes=3)) is not None

    async with training_factory() as session:
        with pytest.raises(TrainingConflictError, match="lease"):
            await PostgresTrainingRepository(session).finish_reminder(stale)

    [_, job] = await _reminder_jobs(training_factory)
    assert job.state == "running"


@pytest.mark.asyncio
async def test_reminder_target_reports_the_thread_of_a_due_cycle(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(training_factory, now - timedelta(seconds=1))
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        await training.remember_thread(CHAT_ID, 33)
        cycle = await training.get_cycle(CHAT_ID)
        assert cycle is not None

        target = await training.reminder_target(CHAT_ID, cycle.id, now)

    assert target == ReminderTarget(thread_id=33)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "blocker", ["not_due", "other_cycle", "disabled", "closed", "open_workflow"]
)
async def test_reminder_target_is_empty_when_the_reminder_does_not_apply(
    training_factory: async_sessionmaker[AsyncSession], blocker: str
) -> None:
    now = datetime.now(UTC)
    await _postpone_to(
        training_factory,
        now + timedelta(days=1) if blocker == "not_due" else now - timedelta(seconds=1),
    )
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        cycle = await training.get_cycle(CHAT_ID)
        assert cycle is not None
        cycle_id = cycle.id + 1 if blocker == "other_cycle" else cycle.id
        if blocker == "disabled":
            await training.set_reminders(CHAT_ID, False)
        elif blocker == "closed":
            await training.close_cycle(CHAT_ID, now)
        elif blocker == "open_workflow":
            await training.start(CHAT_ID, "renewal")

        assert await training.reminder_target(CHAT_ID, cycle_id, now) is None


@pytest.mark.asyncio
async def test_changed_base_plan_marks_proposal_stale(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        conversation = PostgresConversationRepository(session)
        flow = await training.start(CHAT_ID, "exercise_swap")
        current = await conversation.get_current_plan(CHAT_ID)
        flow.draft = current.plan
        flow.report = "swap"
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)
        await conversation.save_training_plan(CHAT_ID, current.plan, "another", "train", "ok", None)
        with pytest.raises(TrainingConflictError, match="no longer current"):
            await training.accept(CHAT_ID, flow.id, datetime.now(UTC))
        assert await training.get_workflow(CHAT_ID) is None
        assert (await conversation.get_current_plan(CHAT_ID)).version == 2


@pytest.mark.asyncio
async def test_callback_accept_checks_revision_inside_transaction(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        flow = await training.start(CHAT_ID, "exercise_swap")
        flow.draft = (await PostgresConversationRepository(session).get_current_plan(CHAT_ID)).plan
        flow.report = "swap"
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)
        with pytest.raises(TrainingConflictError, match="revision changed"):
            await training.accept(CHAT_ID, flow.id, datetime.now(UTC), expected_revision=0)
        await session.rollback()
        assert await training.accept(
            CHAT_ID, flow.id, datetime.now(UTC), expected_revision=flow.revision
        )


@pytest.mark.asyncio
async def test_confirmation_is_atomic_and_swap_preserves_dates() -> None:
    url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    ).replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            conversation = PostgresConversationRepository(session)
            training = PostgresTrainingRepository(session)
            await conversation.restart_interview(CHAT_ID)
            await conversation.save_training_plan(
                CHAT_ID,
                TrainingPlan.model_validate(build_plan_payload()),
                "initial",
                "train",
                "ok",
                None,
            )
            initial = await conversation.get_current_plan(CHAT_ID)
            cycle = await training.get_cycle(CHAT_ID)
            assert initial is not None
            assert cycle is not None
            flow = await training.start(CHAT_ID, "exercise_swap")
            flow.draft = initial.plan
            flow.report = "swap"
            flow.state = "awaiting_confirmation"
            flow = await training.save(CHAT_ID, flow)
            assert (await conversation.get_current_plan(CHAT_ID)).id == initial.id
            accepted = await training.accept(CHAT_ID, flow.id, datetime.now(UTC))
            assert accepted == await training.accept(CHAT_ID, flow.id, datetime.now(UTC))
            current = await conversation.get_current_plan(CHAT_ID)
            assert current is not None
            assert current.version == 2
            assert (await training.get_cycle(CHAT_ID)) == cycle
            next_flow = await training.start(CHAT_ID, "renewal")
            next_flow.draft = current.plan
            next_flow.report = "renewal"
            next_flow.state = "awaiting_confirmation"
            await training.save(CHAT_ID, next_flow)
            with pytest.raises(TrainingConflictError, match="complete"):
                await training.accept(CHAT_ID, next_flow.id, datetime.now(UTC))
            await session.rollback()
            await training.close_cycle(CHAT_ID, datetime.now(UTC))
            await training.accept(CHAT_ID, next_flow.id, datetime.now(UTC))
            assert (await training.get_cycle(CHAT_ID)).id != cycle.id
            await conversation.restart_interview(CHAT_ID)
            await session.execute(
                delete(TrainingMesocycleRecord).where(TrainingMesocycleRecord.chat_id == CHAT_ID)
            )
            await session.execute(
                delete(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
            )
            await session.commit()
    finally:
        await engine.dispose()
