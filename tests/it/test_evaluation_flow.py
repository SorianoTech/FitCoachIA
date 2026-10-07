"""Flujo completo del scheduler (avisos y encuestas semanales) contra contenedores reales.

Plan guardado -> jobs registrados -> `JobScheduler.tick()` (sendMessage/sendPoll al stub de
Telegram) -> voto por el webhook (`poll_answer`) -> nota en `training_evaluation`.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import Bot

from fitcoach.domain.constants import Constants
from fitcoach.domain.scheduled_job import JobState, JobType
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.config.settings import (
    EvaluationSettings,
    SchedulerSettings,
    TrainingSettings,
)
from fitcoach.infrastructure.database.models import (
    JobExecutionRecord,
    ProcessedUpdateRecord,
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.infrastructure.jobs.scheduler import JobScheduler
from tests.unit_test.conftest import build_plan_payload

APP_DB_URL = os.getenv(
    "IT_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
).replace("postgresql://", "postgresql+asyncpg://")
STUB_URL = os.getenv("IT_STUB_URL", f"http://localhost:{os.getenv('IT_STUB_PORT', '9999')}")

CHAT_ID = 882455
UPDATE_IDS = (88245501, 88245502, 88245503)
WEEK = timedelta(days=7)


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(APP_DB_URL)
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
                delete(ProcessedUpdateRecord).where(ProcessedUpdateRecord.update_id.in_(UPDATE_IDS))
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


@pytest.fixture
def stub() -> httpx.Client:
    with httpx.Client(base_url=STUB_URL, timeout=10.0) as stub_client:
        stub_client.get("/__reset")
        yield stub_client


async def _started_days_ago(factory: async_sessionmaker[AsyncSession], days: float) -> None:
    """Move the cycle start back in time, shifting the pending polls with it."""
    started_at = datetime.now(UTC) - timedelta(days=days)
    async with factory() as session:
        cycle_id = await session.scalar(
            select(TrainingMesocycleRecord.id).where(TrainingMesocycleRecord.chat_id == CHAT_ID)
        )
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.id == cycle_id)
            .values(started_at=started_at)
        )
        polls = await session.scalars(
            select(JobExecutionRecord).where(
                JobExecutionRecord.chat_id == CHAT_ID,
                JobExecutionRecord.job_type == JobType.EVALUATION_POLL,
                JobExecutionRecord.state == JobState.PENDING,
            )
        )
        for poll in polls:
            poll.execution_date = started_at + int(str(poll.payload["week_number"])) * WEEK
        await session.commit()


def _scheduler(factory: async_sessionmaker[AsyncSession], bot: Bot) -> JobScheduler:
    return JobScheduler(
        factory,
        bot,
        SchedulerSettings(_env_file=None, enabled=True),
        TrainingSettings(_env_file=None),
        EvaluationSettings(_env_file=None),
    )


def _bot() -> Bot:
    return Bot(token="test-token", base_url=f"{STUB_URL}/bot")  # noqa: S106


async def _tick(factory: async_sessionmaker[AsyncSession]) -> int:
    async with _bot() as bot:
        return await _scheduler(factory, bot).tick()


async def _jobs(
    factory: async_sessionmaker[AsyncSession], job_type: JobType
) -> list[JobExecutionRecord]:
    async with factory() as session:
        return list(
            await session.scalars(
                select(JobExecutionRecord)
                .where(
                    JobExecutionRecord.chat_id == CHAT_ID, JobExecutionRecord.job_type == job_type
                )
                .order_by(JobExecutionRecord.execution_date)
            )
        )


async def _poll_states(factory: async_sessionmaker[AsyncSession]) -> dict[int, str]:
    return {
        int(str(job.payload["week_number"])): job.state
        for job in await _jobs(factory, JobType.EVALUATION_POLL)
    }


async def _evaluation(
    factory: async_sessionmaker[AsyncSession], week: int
) -> TrainingEvaluationRecord:
    async with factory() as session:
        record = await session.scalar(
            select(TrainingEvaluationRecord).where(
                TrainingEvaluationRecord.chat_id == CHAT_ID,
                TrainingEvaluationRecord.week_number == week,
            )
        )
    assert record is not None
    return record


def _vote(update_id: int, poll_id: str, user_id: int, option: int) -> dict[str, object]:
    return {
        "update_id": update_id,
        "poll_answer": {
            "poll_id": poll_id,
            "user": {"id": user_id, "is_bot": False, "first_name": "Ana"},
            "option_ids": [option],
            # Required by Bot API 9.6 (python-telegram-bot >= 22.8).
            "option_persistent_ids": [f"option-{option}"],
        },
    }


# --- polls --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_due_poll_is_sent_and_the_owner_vote_is_stored(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client, client: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)

    assert await _tick(factory) == 1

    [sent] = stub.get("/__polls").json()["sent"]
    assert str(sent["chat_id"]) == str(CHAT_ID)
    assert sent["question"].startswith("Semana 1 de tu plan para ganar músculo")
    assert str(sent["allows_revoting"]).lower() == "false"
    week_one = await _evaluation(factory, 1)
    assert week_one.answer_status == "awaiting"
    assert week_one.goal == "gain_muscle"
    assert week_one.telegram_poll_id is not None

    response = client.post(
        "/webhook/response", json=_vote(UPDATE_IDS[0], week_one.telegram_poll_id, CHAT_ID, 4)
    )

    assert response.status_code == 200
    answered = await _evaluation(factory, 1)
    assert (answered.score, answered.answer_status) == (4, "answered")


@pytest.mark.asyncio
async def test_the_poll_job_is_done_and_linked_to_its_evaluation(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)

    await _tick(factory)

    done = next(job for job in await _jobs(factory, JobType.EVALUATION_POLL) if job.state == "done")
    assert done.executed_at is not None
    assert (await _evaluation(factory, 1)).job_id == done.id
    assert await _tick(factory) == 0


@pytest.mark.asyncio
async def test_a_vote_from_another_user_is_not_stored(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client, client: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)
    await _tick(factory)
    poll_id = (await _evaluation(factory, 1)).telegram_poll_id
    assert poll_id is not None

    response = client.post("/webhook/response", json=_vote(UPDATE_IDS[1], poll_id, CHAT_ID + 1, 5))

    assert response.status_code == 200
    assert (await _evaluation(factory, 1)).score is None


@pytest.mark.asyncio
async def test_nothing_is_sent_before_the_first_week_ends(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    assert await _tick(factory) == 0

    assert stub.get("/__polls").json()["sent"] == []


@pytest.mark.asyncio
async def test_the_next_poll_closes_the_unanswered_one_and_ignores_its_late_vote(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client, client: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)
    await _tick(factory)
    first = await _evaluation(factory, 1)
    await _started_days_ago(factory, 15)

    assert await _tick(factory) == 1

    polls = stub.get("/__polls").json()
    assert [str(stopped["message_id"]) for stopped in polls["stopped"]] == [
        str(first.telegram_message_id)
    ]
    assert (await _evaluation(factory, 1)).answer_status == "unanswered"
    assert (await _evaluation(factory, 2)).answer_status == "awaiting"

    assert first.telegram_poll_id is not None
    response = client.post(
        "/webhook/response", json=_vote(UPDATE_IDS[2], first.telegram_poll_id, CHAT_ID, 5)
    )

    assert response.status_code == 200
    late = await _evaluation(factory, 1)
    assert (late.score, late.answer_status) == (None, "unanswered")


@pytest.mark.asyncio
async def test_after_an_outage_only_the_latest_week_is_sent(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    await _started_days_ago(factory, 22)

    assert await _tick(factory) == 3

    assert len(stub.get("/__polls").json()["sent"]) == 1
    assert await _poll_states(factory) == {
        1: JobState.CANCELLED,
        2: JobState.CANCELLED,
        3: JobState.DONE,
        4: JobState.PENDING,
    }


@pytest.mark.asyncio
async def test_a_poll_whose_cycle_closed_behind_the_back_is_cancelled(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)
    async with factory() as session:
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.chat_id == CHAT_ID)
            .values(completed_at=datetime.now(UTC))
        )
        await session.commit()

    await _tick(factory)

    assert stub.get("/__polls").json()["sent"] == []
    assert (await _poll_states(factory))[1] == JobState.CANCELLED


@pytest.mark.asyncio
async def test_a_poll_sent_after_the_lease_was_lost_leaves_no_evaluation_behind(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    await _started_days_ago(factory, 8)

    async def take_the_lease() -> None:
        async with factory() as session:
            await session.execute(
                update(JobExecutionRecord)
                .where(
                    JobExecutionRecord.chat_id == CHAT_ID,
                    JobExecutionRecord.state == JobState.RUNNING,
                )
                .values(attempts=JobExecutionRecord.attempts + 1)
            )
            await session.commit()

    class LeaseLosingBot:
        """Delegates to the real bot; another scheduler reclaims the job right after sendPoll."""

        def __init__(self, bot: Bot) -> None:
            self._bot = bot

        def __getattr__(self, name: str) -> object:
            return getattr(self._bot, name)

        async def send_poll(self, **kwargs: object) -> object:
            message = await self._bot.send_poll(**kwargs)  # type: ignore[arg-type]
            await take_the_lease()
            return message

    async with _bot() as bot:
        await _scheduler(factory, cast(Bot, LeaseLosingBot(bot))).tick()

    async with factory() as session:
        evaluations = list(
            await session.scalars(
                select(TrainingEvaluationRecord).where(TrainingEvaluationRecord.chat_id == CHAT_ID)
            )
        )
    assert evaluations == []
    assert (await _poll_states(factory))[1] == JobState.RUNNING


# --- reminders ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_due_reminder_is_sent_once_to_the_chat(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    async with factory() as session:
        await PostgresTrainingRepository(session).postpone(
            CHAT_ID, datetime.now(UTC) - timedelta(seconds=1)
        )

    assert await _tick(factory) == 1
    assert await _tick(factory) == 0

    sent = [
        message for message in stub.get("/__sent").json() if str(message["chat_id"]) == str(CHAT_ID)
    ]
    assert [message["text"] for message in sent] == [Constants.TRAINING_DUE_MESSAGE]
    states = [job.state for job in await _jobs(factory, JobType.TRAINING_REMINDER)]
    assert sorted(states) == ["cancelled", "done"]


@pytest.mark.asyncio
async def test_a_reminder_for_a_cycle_with_reminders_off_is_cancelled_without_sending(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    async with factory() as session:
        training = PostgresTrainingRepository(session)
        await training.postpone(CHAT_ID, datetime.now(UTC) - timedelta(seconds=1))
        await training.set_reminders(CHAT_ID, False)

    await _tick(factory)

    sent = [
        message for message in stub.get("/__sent").json() if str(message["chat_id"]) == str(CHAT_ID)
    ]
    assert sent == []
    assert [job.state for job in await _jobs(factory, JobType.TRAINING_REMINDER)] == [
        "cancelled",
        "cancelled",
    ]
