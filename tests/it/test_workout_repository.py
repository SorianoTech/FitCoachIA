import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fitcoach.domain.workout import (
    StartWorkout,
    UpdateWorkout,
    WorkoutConflictError,
    WorkoutNotFoundError,
    WorkoutSession,
    WorkoutValidationError,
)
from fitcoach.infrastructure.database.models import WorkoutRequestRecord, WorkoutSessionRecord
from fitcoach.infrastructure.database.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from fitcoach.infrastructure.database.postgres_workout_repository import PostgresWorkoutRepository
from tests.it.test_training_repository import CHAT_ID
from tests.it.test_training_repository import training_factory as training_factory


async def start_request(factory: async_sessionmaker[AsyncSession]) -> StartWorkout:
    async with factory() as session:
        plan = await PostgresConversationRepository(session).get_current_plan(CHAT_ID)
        assert plan is not None
        return StartWorkout(request_id=uuid4(), plan_id=plan.id, week=1, day=1)


def completed_patch(workout: WorkoutSession) -> UpdateWorkout:
    entries = [item.model_copy(deep=True) for item in workout.exercises]
    for entry in entries:
        for item in entry.sets:
            item.reps = 8
            item.weight_kg = 0.0
            item.rpe = 7.0
            item.completed = True
    return UpdateWorkout(revision=workout.revision, status="completed", exercises=entries)


@pytest.mark.asyncio
async def test_concurrent_start_idempotent_and_single_slot(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await start_request(training_factory)

    async def start(payload: StartWorkout) -> WorkoutSession:
        async with training_factory() as session:
            return await PostgresWorkoutRepository(session).start(CHAT_ID, payload)

    results = await asyncio.gather(
        start(request), start(request), start(request.model_copy(update={"request_id": uuid4()}))
    )
    assert len({item.id for item in results}) == 1
    assert results[0].prescription.exercises[0].exercise_id == 101
    assert [item.number for item in results[0].exercises[0].sets] == [1, 2, 3]
    async with training_factory() as session:
        repository = PostgresWorkoutRepository(session)
        assert len(await repository.list_sessions(CHAT_ID)) == 1
        with pytest.raises(WorkoutConflictError, match="UUID"):
            await repository.start(CHAT_ID, request.model_copy(update={"day": 2}))


@pytest.mark.asyncio
async def test_swap_resumes_frozen_snapshot_and_remembers_resume_uuid(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await start_request(training_factory)
    async with training_factory() as session:
        repository = PostgresWorkoutRepository(session)
        original = await repository.start(CHAT_ID, request)
        conversation = PostgresConversationRepository(session)
        current = await conversation.get_current_plan(CHAT_ID)
        assert current is not None
        changed = current.plan.model_copy(deep=True)
        changed.weeks[0].days[0].exercises[0].exercise_id = 102
        # Existing save_training_plan opens a new cycle; an accepted swap keeps it.
        from fitcoach.infrastructure.database.models import (
            TrainingPlanRecord,
            TrainingSessionRecord,
        )

        new_plan = TrainingPlanRecord(
            chat_id=CHAT_ID,
            version=2,
            mesocycle_id=original.mesocycle_id,
            parent_plan_id=current.id,
            change_kind="exercise_swap",
            plan=changed.model_dump(mode="json"),
            report="swap",
        )
        session.add(new_plan)
        await session.flush()
        active = await session.get(TrainingSessionRecord, CHAT_ID)
        assert active is not None
        active.current_plan_id = new_plan.id
        await session.commit()
        resume = request.model_copy(update={"request_id": uuid4(), "plan_id": new_plan.id})
        resumed = await repository.start(CHAT_ID, resume)
        assert resumed.id == original.id
        assert resumed.plan_id == original.plan_id
        assert resumed.prescription == original.prescription
        assert (await repository.start(CHAT_ID, request)).id == original.id
        assert (await repository.start(CHAT_ID, resume)).id == original.id
        with pytest.raises(WorkoutConflictError, match="UUID"):
            await repository.start(CHAT_ID, resume.model_copy(update={"day": 2}))
        await session.rollback()
        with pytest.raises(WorkoutConflictError, match="no longer current"):
            await repository.start(CHAT_ID, request.model_copy(update={"request_id": uuid4()}))


@pytest.mark.asyncio
async def test_ownership_validation_completion_and_real_summary(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await start_request(training_factory)
    async with training_factory() as session:
        repository = PostgresWorkoutRepository(session)
        started = await repository.start(CHAT_ID, request)
        assert await repository.list_sessions(CHAT_ID + 1) == []
        with pytest.raises(WorkoutNotFoundError):
            await repository.get(CHAT_ID + 1, started.id)
        with pytest.raises(WorkoutNotFoundError):
            await repository.start(CHAT_ID + 1, request)
        await session.rollback()
        assert started.mesocycle_id is not None
        empty = await repository.performance_summary(CHAT_ID, started.mesocycle_id)
        assert empty["completed_sessions"] == 0
        incomplete = UpdateWorkout(revision=0, status="completed", exercises=started.exercises)
        with pytest.raises(WorkoutValidationError):
            await repository.update(CHAT_ID, started.id, incomplete)
        await session.rollback()
        done = await repository.update(CHAT_ID, started.id, completed_patch(started))
        assert done.revision == 1
        assert done.completed_at is not None
        summary = await repository.performance_summary(CHAT_ID, started.mesocycle_id)
        assert summary["completed_sessions"] == 1
        assert summary["truncated"] is False
        assert summary["completed_slots"][0]["week"] == 1
        assert summary["measurements"][0]["sets"][0]["weight_kg"] == 0.0
        with pytest.raises(WorkoutConflictError, match="read-only"):
            await repository.update(CHAT_ID, started.id, completed_patch(done))
        await session.rollback()
        current = await PostgresConversationRepository(session).get_current_plan(CHAT_ID)
        assert current is not None
        assert current.plan.weeks[0].days[0] == started.prescription


@pytest.mark.asyncio
async def test_concurrent_edits_return_one_explicit_revision_conflict(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await start_request(training_factory)
    async with training_factory() as session:
        started = await PostgresWorkoutRepository(session).start(CHAT_ID, request)

    async def update() -> WorkoutSession | WorkoutConflictError:
        async with training_factory() as session:
            try:
                return await PostgresWorkoutRepository(session).update(
                    CHAT_ID, started.id, completed_patch(started)
                )
            except WorkoutConflictError as error:
                await session.rollback()
                return error

    results = await asyncio.gather(update(), update())
    assert sum(isinstance(item, WorkoutConflictError) for item in results) == 1
    assert sum(isinstance(item, WorkoutSession) for item in results) == 1


@pytest.mark.asyncio
async def test_reset_cascades_sessions_and_uuid_aliases(
    training_factory: async_sessionmaker[AsyncSession],
) -> None:
    request = await start_request(training_factory)
    async with training_factory() as session:
        repository = PostgresWorkoutRepository(session)
        started = await repository.start(CHAT_ID, request)
        await repository.start(CHAT_ID, request.model_copy(update={"request_id": uuid4()}))
        await PostgresConversationRepository(session).restart_interview(CHAT_ID)
        assert await repository.list_sessions(CHAT_ID) == []
        assert (
            await session.scalar(
                select(WorkoutRequestRecord).where(WorkoutRequestRecord.chat_id == CHAT_ID)
            )
            is None
        )
        assert (
            await session.scalar(
                select(WorkoutSessionRecord).where(WorkoutSessionRecord.id == started.id)
            )
            is None
        )
