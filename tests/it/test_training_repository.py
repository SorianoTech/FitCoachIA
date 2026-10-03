import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.infrastructure.database.models import TrainingMesocycleRecord
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_training_repository import PostgresTrainingRepository
from fitcoach.repository.training_repository import TrainingConflictError
from tests.unit_test.conftest import build_plan_payload

CHAT_ID = 882299


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
