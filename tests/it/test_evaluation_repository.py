import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_evaluation import EvaluationState
from fitcoach.infrastructure.database.models import (
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
    TrainingPlanRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.repository.evaluation_repository import EvaluationConflictError, EvaluationDelivery
from tests.unit_test.conftest import build_plan_payload

CHAT_ID = 882377
TIMEOUT = timedelta(minutes=2)
WEEK = timedelta(days=7)


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
            # /interview keeps evaluations on purpose, so the test removes them itself.
            await session.execute(
                delete(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
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


async def _cycle(session: AsyncSession) -> TrainingMesocycleRecord:
    cycle = await session.scalar(
        select(TrainingMesocycleRecord)
        .where(TrainingMesocycleRecord.chat_id == CHAT_ID)
        .order_by(TrainingMesocycleRecord.id.desc())
        .limit(1)
    )
    assert cycle is not None
    return cycle


async def _start_days_ago(
    factory: async_sessionmaker[AsyncSession], days: float, **cycle_values: object
) -> datetime:
    """Move the cycle start back in time, shifting its scheduled polls with it."""
    started_at = datetime.now(UTC) - timedelta(days=days)
    async with factory() as session:
        cycle = await _cycle(session)
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.id == cycle.id)
            .values(started_at=started_at, **cycle_values)
        )
        polls = await session.scalars(
            select(TrainingEvaluationRecord).where(
                TrainingEvaluationRecord.mesocycle_id == cycle.id,
                TrainingEvaluationRecord.state == EvaluationState.PENDING,
            )
        )
        for poll in polls:
            poll.due_at = started_at + poll.week_number * WEEK
        await session.commit()
    return started_at


async def _evaluations(factory: async_sessionmaker[AsyncSession]) -> list[TrainingEvaluationRecord]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(TrainingEvaluationRecord)
                .where(TrainingEvaluationRecord.chat_id == CHAT_ID)
                .order_by(TrainingEvaluationRecord.id)
            )
        )


async def _states(factory: async_sessionmaker[AsyncSession]) -> dict[int, str]:
    return {e.week_number: e.state for e in await _evaluations(factory)}


async def _claim(factory: async_sessionmaker[AsyncSession]) -> EvaluationDelivery | None:
    async with factory() as session:
        return await PostgresEvaluationRepository(session).claim(datetime.now(UTC), TIMEOUT)


async def _mark_sent(
    factory: async_sessionmaker[AsyncSession], delivery: EvaluationDelivery | None, poll_id: str
) -> None:
    assert delivery is not None
    async with factory() as session:
        await PostgresEvaluationRepository(session).mark_sent(
            delivery, poll_id, 1000 + delivery.week_number, datetime.now(UTC)
        )


async def _accept_current_plan_as(
    factory: async_sessionmaker[AsyncSession], kind: str, start: datetime
) -> None:
    async with factory() as session:
        training = PostgresTrainingRepository(session)
        current = await PostgresConversationRepository(session).get_current_plan(CHAT_ID)
        assert current is not None
        flow = await training.start(CHAT_ID, kind)
        flow.draft = current.plan
        flow.report = kind
        flow.state = "awaiting_confirmation"
        await training.save(CHAT_ID, flow)
        await training.accept(CHAT_ID, flow.id, start)


# --- scheduling ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_a_plan_copies_its_goal(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        goal = await session.scalar(
            select(TrainingPlanRecord.goal).where(TrainingPlanRecord.chat_id == CHAT_ID)
        )
    assert goal == "gain_muscle"


@pytest.mark.asyncio
async def test_the_first_plan_schedules_four_weekly_polls(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        started_at = (await _cycle(session)).started_at
    assert started_at is not None

    evaluations = await _evaluations(factory)

    assert [e.week_number for e in evaluations] == [1, 2, 3, 4]
    assert {e.state for e in evaluations} == {EvaluationState.PENDING}
    assert [e.due_at for e in evaluations] == [started_at + k * WEEK for k in (1, 2, 3, 4)]
    # Goal and plan are taken when the poll is sent, not when it is scheduled.
    assert {(e.goal, e.plan_id) for e in evaluations} == {(None, None)}


@pytest.mark.asyncio
async def test_a_plan_change_within_the_cycle_schedules_nothing_new(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    before = [(e.id, e.due_at) for e in await _evaluations(factory)]

    await _accept_current_plan_as(factory, "exercise_swap", datetime.now(UTC))

    assert [(e.id, e.due_at) for e in await _evaluations(factory)] == before


@pytest.mark.asyncio
async def test_renewal_cancels_the_old_cycle_and_schedules_the_new_one(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        old_cycle_id = (await _cycle(session)).id
        await PostgresTrainingRepository(session).close_cycle(CHAT_ID, datetime.now(UTC))
    start = datetime.now(UTC) + timedelta(days=1)

    await _accept_current_plan_as(factory, "renewal", start)

    async with factory() as session:
        new_cycle_id = (await _cycle(session)).id
    evaluations = await _evaluations(factory)
    old = [e for e in evaluations if e.mesocycle_id == old_cycle_id]
    new = [e for e in evaluations if e.mesocycle_id == new_cycle_id]
    assert new_cycle_id != old_cycle_id
    assert {e.state for e in old} == {EvaluationState.CANCELLED}
    assert [e.week_number for e in new] == [1, 2, 3, 4]
    assert {e.state for e in new} == {EvaluationState.PENDING}
    assert new[0].due_at == start + WEEK


@pytest.mark.asyncio
async def test_closing_the_cycle_early_cancels_only_its_pending_polls(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    await _mark_sent(factory, await _claim(factory), "poll-week-1")

    async with factory() as session:
        await PostgresTrainingRepository(session).close_cycle(CHAT_ID, datetime.now(UTC))

    assert await _states(factory) == {
        1: EvaluationState.SENT,
        2: EvaluationState.CANCELLED,
        3: EvaluationState.CANCELLED,
        4: EvaluationState.CANCELLED,
    }


@pytest.mark.asyncio
async def test_postponing_schedules_no_extra_poll(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    before = [(e.id, e.due_at, e.state) for e in await _evaluations(factory)]

    async with factory() as session:
        await PostgresTrainingRepository(session).postpone(
            CHAT_ID, datetime.now(UTC) + timedelta(days=40)
        )

    assert [(e.id, e.due_at, e.state) for e in await _evaluations(factory)] == before


@pytest.mark.asyncio
async def test_a_legacy_cycle_receiving_a_start_schedules_only_its_future_weeks(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        cycle = await _cycle(session)
        await session.execute(
            delete(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
        )
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.id == cycle.id)
            .values(started_at=None, expected_end_at=None)
        )
        await session.commit()

    async with factory() as session:
        await PostgresTrainingRepository(session).set_start(
            CHAT_ID, datetime.now(UTC) - timedelta(days=10)
        )

    assert await _states(factory) == {
        2: EvaluationState.PENDING,
        3: EvaluationState.PENDING,
        4: EvaluationState.PENDING,
    }


@pytest.mark.asyncio
async def test_restarting_the_interview_cancels_pending_polls_but_keeps_them(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    await _mark_sent(factory, await _claim(factory), "poll-week-1")

    async with factory() as session:
        await PostgresConversationRepository(session).restart_interview(CHAT_ID)

    evaluations = await _evaluations(factory)
    assert {e.week_number: e.state for e in evaluations} == {
        1: EvaluationState.SENT,
        2: EvaluationState.CANCELLED,
        3: EvaluationState.CANCELLED,
        4: EvaluationState.CANCELLED,
    }
    assert {e.mesocycle_id for e in evaluations} == {None}
    assert evaluations[0].goal == "gain_muscle"


# --- claim --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nothing_is_claimed_before_the_first_week_ends(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 6)

    assert await _claim(factory) is None
    assert set((await _states(factory)).values()) == {EvaluationState.PENDING}


@pytest.mark.asyncio
async def test_claim_locks_the_poll_and_copies_the_current_plan(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8, message_thread_id=42)

    delivery = await _claim(factory)

    assert delivery is not None
    assert delivery.chat_id == CHAT_ID
    assert delivery.thread_id == 42
    assert delivery.week_number == 1
    assert delivery.goal == "gain_muscle"
    assert delivery.attempts == 1
    assert delivery.previous_message_id is None
    async with factory() as session:
        plan_id = await session.scalar(
            select(TrainingPlanRecord.id).where(TrainingPlanRecord.chat_id == CHAT_ID)
        )
    first = (await _evaluations(factory))[0]
    assert first.state == EvaluationState.SENDING
    assert first.locked_until is not None
    assert first.goal == "gain_muscle"
    assert first.plan_id == plan_id


@pytest.mark.asyncio
async def test_after_an_outage_only_the_latest_week_is_sent(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 22)

    delivery = await _claim(factory)

    assert delivery is not None
    assert delivery.week_number == 3
    assert await _states(factory) == {
        1: EvaluationState.CANCELLED,
        2: EvaluationState.CANCELLED,
        3: EvaluationState.SENDING,
        4: EvaluationState.PENDING,
    }


@pytest.mark.asyncio
async def test_disabled_reminders_do_not_stop_the_polls(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8, reminders_enabled=False)

    delivery = await _claim(factory)

    assert delivery is not None
    assert delivery.week_number == 1


@pytest.mark.asyncio
async def test_two_workers_never_claim_the_same_poll(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)

    first, second = await asyncio.gather(_claim(factory), _claim(factory))

    assert [first is None, second is None].count(True) == 1


@pytest.mark.asyncio
async def test_a_poll_whose_cycle_closed_is_cancelled_on_claim(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # Closed behind close_cycle's back: the claim is the last safety net.
    await _start_days_ago(factory, 8, completed_at=datetime.now(UTC))

    assert await _claim(factory) is None

    assert (await _states(factory))[1] == EvaluationState.CANCELLED


@pytest.mark.asyncio
async def test_claim_reports_the_previous_unanswered_poll_to_close(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    await _mark_sent(factory, await _claim(factory), "poll-week-1")
    await _start_days_ago(factory, 15)

    second = await _claim(factory)

    assert second is not None
    assert second.week_number == 2
    assert second.previous_message_id == 1001


@pytest.mark.asyncio
async def test_an_answered_previous_poll_is_not_reported_to_close(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    await _mark_sent(factory, await _claim(factory), "poll-week-1")
    await _answer(factory, "poll-week-1", CHAT_ID, 3)
    await _start_days_ago(factory, 15)

    second = await _claim(factory)

    assert second is not None
    assert second.previous_message_id is None


# --- mark_sent / finish -------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_sent_stores_the_telegram_identifiers(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)

    await _mark_sent(factory, await _claim(factory), "poll-1")

    first = (await _evaluations(factory))[0]
    assert first.state == EvaluationState.SENT
    assert first.telegram_poll_id == "poll-1"
    assert first.telegram_message_id == 1001
    assert first.sent_at is not None
    assert first.locked_until is None


@pytest.mark.asyncio
async def test_finish_with_retry_reschedules_the_poll(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    delivery = await _claim(factory)
    assert delivery is not None
    retry_at = datetime.now(UTC) + timedelta(minutes=10)

    async with factory() as session:
        await PostgresEvaluationRepository(session).finish(delivery, retry_at=retry_at)

    first = (await _evaluations(factory))[0]
    assert first.state == EvaluationState.PENDING
    assert first.due_at == retry_at
    assert await _claim(factory) is None


@pytest.mark.asyncio
async def test_finish_as_failed_stops_retrying(factory: async_sessionmaker[AsyncSession]) -> None:
    await _start_days_ago(factory, 8)
    delivery = await _claim(factory)
    assert delivery is not None

    async with factory() as session:
        await PostgresEvaluationRepository(session).finish(delivery, failed=True)

    assert (await _states(factory))[1] == EvaluationState.FAILED
    assert await _claim(factory) is None


@pytest.mark.asyncio
async def test_a_worker_whose_lock_expired_cannot_finish_the_poll(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _start_days_ago(factory, 8)
    stale = await _claim(factory)
    assert stale is not None
    async with factory() as session:
        await session.execute(
            update(TrainingEvaluationRecord)
            .where(TrainingEvaluationRecord.id == stale.id)
            .values(locked_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    assert await _claim(factory) is not None

    async with factory() as session:
        with pytest.raises(EvaluationConflictError):
            await PostgresEvaluationRepository(session).mark_sent(
                stale, "poll-stale", 1, datetime.now(UTC)
            )


# --- record_answer ------------------------------------------------------------


async def _sent_poll(factory: async_sessionmaker[AsyncSession]) -> None:
    await _start_days_ago(factory, 8)
    await _mark_sent(factory, await _claim(factory), "poll-answer")


async def _answer(
    factory: async_sessionmaker[AsyncSession], poll_id: str, user_id: int, score: int | None
) -> bool:
    async with factory() as session:
        return await PostgresEvaluationRepository(session).record_answer(
            poll_id, user_id, score, datetime.now(UTC)
        )


@pytest.mark.asyncio
async def test_the_owner_answer_is_stored(factory: async_sessionmaker[AsyncSession]) -> None:
    await _sent_poll(factory)

    assert await _answer(factory, "poll-answer", CHAT_ID, 4)

    first = (await _evaluations(factory))[0]
    assert first.score == 4
    assert first.answered_at is not None


@pytest.mark.asyncio
async def test_a_retracted_vote_clears_the_score(factory: async_sessionmaker[AsyncSession]) -> None:
    await _sent_poll(factory)
    await _answer(factory, "poll-answer", CHAT_ID, 4)

    assert await _answer(factory, "poll-answer", CHAT_ID, None)

    first = (await _evaluations(factory))[0]
    assert first.score is None
    assert first.answered_at is None


@pytest.mark.asyncio
async def test_an_answer_from_another_user_is_ignored(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _sent_poll(factory)

    assert not await _answer(factory, "poll-answer", CHAT_ID + 1, 5)

    assert (await _evaluations(factory))[0].score is None


@pytest.mark.asyncio
async def test_an_answer_to_an_unknown_poll_is_ignored(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    assert not await _answer(factory, "missing-poll", CHAT_ID, 3)
