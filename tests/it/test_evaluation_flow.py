"""Flujo completo de las encuestas semanales contra contenedores reales.

Plan guardado -> 4 encuestas programadas -> worker `evaluation` (sendPoll al stub de
Telegram) -> voto por el webhook (`poll_answer`) -> nota en `training_evaluation`.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from telegram import Bot

from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.config.settings import EvaluationSettings
from fitcoach.infrastructure.database.models import (
    ProcessedUpdateRecord,
    TrainingEvaluationRecord,
    TrainingMesocycleRecord,
)
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from fitcoach.infrastructure.jobs.evaluation import run_batch
from tests.unit_test.conftest import build_plan_payload

APP_DB_URL = os.getenv(
    "IT_DB_URL",
    f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
).replace("postgresql://", "postgresql+asyncpg://")
STUB_URL = os.getenv("IT_STUB_URL", f"http://localhost:{os.getenv('IT_STUB_PORT', '9999')}")

CHAT_ID = 882455
UPDATE_IDS = (88245501, 88245502)


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


async def _first_week_is_due(factory: async_sessionmaker[AsyncSession]) -> None:
    started_at = datetime.now(UTC) - timedelta(days=8)
    async with factory() as session:
        cycle_id = await session.scalar(
            select(TrainingMesocycleRecord.id).where(TrainingMesocycleRecord.chat_id == CHAT_ID)
        )
        await session.execute(
            update(TrainingMesocycleRecord)
            .where(TrainingMesocycleRecord.id == cycle_id)
            .values(started_at=started_at)
        )
        for poll in await session.scalars(
            select(TrainingEvaluationRecord).where(
                TrainingEvaluationRecord.mesocycle_id == cycle_id
            )
        ):
            poll.due_at = started_at + poll.week_number * timedelta(days=7)
        await session.commit()


async def _run_worker(factory: async_sessionmaker[AsyncSession]) -> int:
    async with Bot(
        token="test-token",  # noqa: S106
        base_url=f"{STUB_URL}/bot",
    ) as bot:
        async with factory() as session:
            return await run_batch(
                PostgresEvaluationRepository(session),
                bot,
                EvaluationSettings(_env_file=None, enabled=True),
            )


async def _week_one(factory: async_sessionmaker[AsyncSession]) -> TrainingEvaluationRecord:
    async with factory() as session:
        record = await session.scalar(
            select(TrainingEvaluationRecord).where(
                TrainingEvaluationRecord.chat_id == CHAT_ID,
                TrainingEvaluationRecord.week_number == 1,
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


@pytest.mark.asyncio
async def test_a_due_poll_is_sent_and_the_owner_vote_is_stored(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client, client: httpx.Client
) -> None:
    await _first_week_is_due(factory)

    assert await _run_worker(factory) == 1

    [sent] = stub.get("/__polls").json()["sent"]
    assert str(sent["chat_id"]) == str(CHAT_ID)
    assert sent["question"].startswith("Semana 1 de tu plan para ganar músculo")
    assert str(sent["allows_revoting"]).lower() == "false"
    week_one = await _week_one(factory)
    assert week_one.state == "sent"
    assert week_one.goal == "gain_muscle"
    assert week_one.telegram_poll_id is not None

    response = client.post(
        "/webhook/response", json=_vote(UPDATE_IDS[0], week_one.telegram_poll_id, CHAT_ID, 4)
    )

    assert response.status_code == 200
    assert (await _week_one(factory)).score == 4


@pytest.mark.asyncio
async def test_a_vote_from_another_user_is_not_stored(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client, client: httpx.Client
) -> None:
    await _first_week_is_due(factory)
    await _run_worker(factory)
    poll_id = (await _week_one(factory)).telegram_poll_id
    assert poll_id is not None

    response = client.post("/webhook/response", json=_vote(UPDATE_IDS[1], poll_id, CHAT_ID + 1, 5))

    assert response.status_code == 200
    assert (await _week_one(factory)).score is None


@pytest.mark.asyncio
async def test_nothing_is_sent_before_the_first_week_ends(
    factory: async_sessionmaker[AsyncSession], stub: httpx.Client
) -> None:
    assert await _run_worker(factory) == 0

    assert stub.get("/__polls").json()["sent"] == []
