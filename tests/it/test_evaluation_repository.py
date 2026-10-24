import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.scheduled_job import evaluation_poll_key
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_evaluation import AnswerStatus
from fitcoach.infrastructure.database.models import (
    JobExecutionRecord,
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
from fitcoach.repository.evaluation_repository import PollTarget, SentPoll
from tests.unit_test.conftest import build_plan_payload

CHAT_ID = 882377


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
            await session.execute(
                delete(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
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


async def _cycle_id(factory: async_sessionmaker[AsyncSession]) -> int:
    async with factory() as session:
        cycle_id = await session.scalar(
            select(TrainingMesocycleRecord.id)
            .where(TrainingMesocycleRecord.chat_id == CHAT_ID)
            .order_by(TrainingMesocycleRecord.id.desc())
            .limit(1)
        )
    assert cycle_id is not None
    return cycle_id


async def _target(factory: async_sessionmaker[AsyncSession]) -> PollTarget:
    async with factory() as session:
        target = await PostgresEvaluationRepository(session).open_current_plan(
            await _cycle_id(factory)
        )
    assert target is not None
    return target


async def _send(
    factory: async_sessionmaker[AsyncSession], week: int, poll_id: str | None = None
) -> SentPoll:
    """Record the poll of ``week`` the way the scheduler does: flush, then commit."""
    cycle_id = await _cycle_id(factory)
    async with factory() as session:
        job_id = await session.scalar(
            select(JobExecutionRecord.id).where(
                JobExecutionRecord.dedup_key == evaluation_poll_key(cycle_id, week)
            )
        )
        assert job_id is not None
        poll = SentPoll(
            job_id=job_id,
            chat_id=CHAT_ID,
            target=await _target(factory),
            week_number=week,
            poll_id=poll_id or f"poll-week-{week}",
            message_id=1000 + week,
            sent_at=datetime.now(UTC),
        )
        await PostgresEvaluationRepository(session).save_sent(poll)
        await session.commit()
    return poll


async def _evaluations(factory: async_sessionmaker[AsyncSession]) -> list[TrainingEvaluationRecord]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(TrainingEvaluationRecord)
                .where(TrainingEvaluationRecord.chat_id == CHAT_ID)
                .order_by(TrainingEvaluationRecord.week_number)
            )
        )


async def _statuses(factory: async_sessionmaker[AsyncSession]) -> dict[int, str]:
    return {e.week_number: e.answer_status for e in await _evaluations(factory)}


async def _answer(
    factory: async_sessionmaker[AsyncSession], poll_id: str, user_id: int, score: int | None
) -> bool:
    async with factory() as session:
        return await PostgresEvaluationRepository(session).record_answer(
            poll_id, user_id, score, datetime.now(UTC)
        )


async def _previous_unanswered(factory: async_sessionmaker[AsyncSession]) -> list[int]:
    async with factory() as session:
        return await PostgresEvaluationRepository(session).previous_unanswered(CHAT_ID)


# --- open_current_plan --------------------------------------------------------


@pytest.mark.asyncio
async def test_saving_a_plan_copies_its_goal(factory: async_sessionmaker[AsyncSession]) -> None:
    async with factory() as session:
        goal = await session.scalar(
            select(TrainingPlanRecord.goal).where(TrainingPlanRecord.chat_id == CHAT_ID)
        )
    assert goal == "gain_muscle"


@pytest.mark.asyncio
async def test_the_open_cycle_reports_its_current_plan_and_goal(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        await PostgresTrainingRepository(session).remember_thread(CHAT_ID, 42)

    target = await _target(factory)

    assert (target.thread_id, target.goal) == (42, "gain_muscle")
    assert target.started_at is not None
    async with factory() as session:
        plan_id = await session.scalar(
            select(TrainingPlanRecord.id).where(TrainingPlanRecord.chat_id == CHAT_ID)
        )
    assert target.plan_id == plan_id


@pytest.mark.asyncio
async def test_a_closed_cycle_has_no_open_plan(factory: async_sessionmaker[AsyncSession]) -> None:
    cycle_id = await _cycle_id(factory)
    async with factory() as session:
        await PostgresTrainingRepository(session).close_cycle(CHAT_ID, datetime.now(UTC))

    async with factory() as session:
        assert await PostgresEvaluationRepository(session).open_current_plan(cycle_id) is None


@pytest.mark.asyncio
async def test_an_unknown_cycle_has_no_open_plan(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        assert await PostgresEvaluationRepository(session).open_current_plan(-1) is None


# --- save_sent ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_sent_stores_the_telegram_identifiers_and_the_job_link(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    poll = await _send(factory, 1, "poll-1")

    [first] = await _evaluations(factory)

    assert first.answer_status == AnswerStatus.AWAITING
    assert (first.telegram_poll_id, first.telegram_message_id) == ("poll-1", 1001)
    assert (first.goal, first.plan_id, first.job_id) == (
        "gain_muscle",
        poll.target.plan_id,
        poll.job_id,
    )
    assert first.sent_at is not None


@pytest.mark.asyncio
async def test_save_sent_closes_the_unanswered_polls_of_the_chat(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)
    await _send(factory, 2)
    await _answer(factory, "poll-week-2", CHAT_ID, 4)

    await _send(factory, 3)

    assert await _statuses(factory) == {
        1: AnswerStatus.UNANSWERED,
        2: AnswerStatus.ANSWERED,
        3: AnswerStatus.AWAITING,
    }


@pytest.mark.asyncio
async def test_save_sent_does_not_persist_until_the_caller_commits(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)
    cycle_id = await _cycle_id(factory)
    async with factory() as session:
        job_id = await session.scalar(
            select(JobExecutionRecord.id).where(
                JobExecutionRecord.dedup_key == evaluation_poll_key(cycle_id, 2)
            )
        )
        assert job_id is not None
        poll = SentPoll(
            job_id=job_id,
            chat_id=CHAT_ID,
            target=await _target(factory),
            week_number=2,
            poll_id="poll-uncommitted",
            message_id=1002,
            sent_at=datetime.now(UTC),
        )
        await PostgresEvaluationRepository(session).save_sent(poll)
        await session.rollback()

    assert await _statuses(factory) == {1: AnswerStatus.AWAITING}


@pytest.mark.asyncio
async def test_a_week_can_be_recorded_only_once(factory: async_sessionmaker[AsyncSession]) -> None:
    await _send(factory, 1, "poll-1")

    with pytest.raises(IntegrityError):
        await _send(factory, 1, "poll-1-again")


# --- previous_unanswered ------------------------------------------------------


@pytest.mark.asyncio
async def test_there_is_no_previous_poll_before_the_first_one(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    assert await _previous_unanswered(factory) == []


@pytest.mark.asyncio
async def test_unanswered_polls_are_reported_to_be_closed(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)

    assert await _previous_unanswered(factory) == [1001]


@pytest.mark.asyncio
async def test_answered_and_closed_polls_are_not_reported(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)
    await _send(factory, 2)
    await _answer(factory, "poll-week-2", CHAT_ID, 3)

    assert await _previous_unanswered(factory) == []


# --- record_answer ------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_owner_answer_is_stored(factory: async_sessionmaker[AsyncSession]) -> None:
    await _send(factory, 1, "poll-answer")

    assert await _answer(factory, "poll-answer", CHAT_ID, 4)

    [first] = await _evaluations(factory)
    assert (first.score, first.answer_status) == (4, AnswerStatus.ANSWERED)
    assert first.answered_at is not None


@pytest.mark.asyncio
async def test_a_retracted_vote_clears_the_score(factory: async_sessionmaker[AsyncSession]) -> None:
    await _send(factory, 1, "poll-answer")
    await _answer(factory, "poll-answer", CHAT_ID, 4)

    assert await _answer(factory, "poll-answer", CHAT_ID, None)

    [first] = await _evaluations(factory)
    assert (first.score, first.answered_at, first.answer_status) == (
        None,
        None,
        AnswerStatus.AWAITING,
    )


@pytest.mark.asyncio
async def test_an_answer_from_another_user_is_ignored(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1, "poll-answer")

    assert not await _answer(factory, "poll-answer", CHAT_ID + 1, 5)

    [first] = await _evaluations(factory)
    assert (first.score, first.answer_status) == (None, AnswerStatus.AWAITING)


@pytest.mark.asyncio
async def test_an_answer_to_an_unknown_poll_is_ignored(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    assert not await _answer(factory, "missing-poll", CHAT_ID, 3)


@pytest.mark.asyncio
async def test_a_late_vote_on_a_closed_poll_is_ignored(
    factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    await _send(factory, 1)
    await _send(factory, 2)

    with caplog.at_level("INFO"):
        assert not await _answer(factory, "poll-week-1", CHAT_ID, 5)

    assert (await _evaluations(factory))[0].score is None
    assert await _statuses(factory) == {1: AnswerStatus.UNANSWERED, 2: AnswerStatus.AWAITING}
    assert any("Late vote" in record.getMessage() for record in caplog.records)


# --- /interview ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_restarting_the_interview_keeps_sent_polls_detached_from_the_cycle(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)

    async with factory() as session:
        await PostgresConversationRepository(session).restart_interview(CHAT_ID)

    [first] = await _evaluations(factory)
    assert (first.mesocycle_id, first.plan_id, first.goal) == (None, None, "gain_muscle")


@pytest.mark.asyncio
async def test_sent_polls_outlive_the_deletion_of_their_job(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    await _send(factory, 1)

    async with factory() as session:
        await session.execute(
            delete(JobExecutionRecord).where(JobExecutionRecord.chat_id == CHAT_ID)
        )
        await session.commit()

    [first] = await _evaluations(factory)
    assert first.job_id is None
