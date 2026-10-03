import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.database.models import (
    TrainingMesocycleRecord,
    TrainingNotificationRecord,
    TrainingPlanRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.repository.training_repository import TrainingConflictError
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


@pytest.mark.asyncio
async def test_postponing_before_first_reminder_does_not_double_notify(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        await training.postpone(CHAT_ID, now + timedelta(days=1))
        await training.enqueue_due(now + timedelta(days=2))
        delivery = await training.claim_reminder(now + timedelta(days=2))
        assert delivery is not None
        assert delivery.chat_id == CHAT_ID
        await training.finish_reminder(delivery)
        assert await training.claim_reminder(now + timedelta(days=2)) is None
        events = list(await session.scalars(select(TrainingNotificationRecord.state)))
        assert "cancelled" in events
        assert "sent" in events


@pytest.mark.asyncio
async def test_interaction_and_worker_share_one_delivery_reservation(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with training_factory() as session:
        training = PostgresTrainingRepository(session)
        await training.postpone(CHAT_ID, now - timedelta(seconds=1))
        delivery = await training.reserve_interaction_reminder(CHAT_ID, 22, now)
        assert delivery is not None
        assert delivery.thread_id == 22
        assert await training.claim_reminder(now) is None
        await training.finish_reminder(delivery)
        assert await training.reserve_interaction_reminder(CHAT_ID, 22, now) is None


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
            await session.commit()
    finally:
        await engine.dispose()
