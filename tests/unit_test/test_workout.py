from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from fitcoach.domain.trainer_plan import TrainingDay, TrainingPlan
from fitcoach.domain.workout import (
    StartWorkout,
    UpdateWorkout,
    WorkoutExercise,
    WorkoutNotFoundError,
    WorkoutSession,
    WorkoutSet,
    WorkoutValidationError,
)
from fitcoach.infrastructure.database.postgres_workout_repository import PostgresWorkoutRepository
from fitcoach.repository.conversation_repository import StoredTrainingPlan
from fitcoach.service.workout_service import WorkoutService
from tests.unit_test.conftest import build_plan_payload


def prescription() -> TrainingDay:
    return TrainingPlan.model_validate(build_plan_payload()).weeks[0].days[0]


def actual(*, completed: bool = True) -> WorkoutExercise:
    return WorkoutExercise(
        position=0,
        skipped=False,
        sets=[
            WorkoutSet(number=n, reps=8 if completed else None, completed=completed)
            for n in range(1, 4)
        ],
    )


def workout(*, session_id: int = 1, completed: bool = True) -> WorkoutSession:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    return WorkoutSession(
        id=session_id,
        plan_id=1,
        mesocycle_id=1,
        week=1,
        day=1,
        revision=0,
        status="completed" if completed else "in_progress",
        started_at=now,
        completed_at=now if completed else None,
        prescription=prescription(),
        exercises=[actual(completed=completed)],
    )


@pytest.mark.parametrize(
    "change",
    [
        {"number": 0},
        {"number": 11},
        {"reps": -1},
        {"reps": 0},
        {"reps": 10001},
        {"reps": True},
        {"duration_seconds": -1},
        {"duration_seconds": 0},
        {"duration_seconds": 86401},
        {"weight_kg": -1.0},
        {"weight_kg": 2001.0},
        {"weight_kg": float("nan")},
        {"weight_kg": float("inf")},
        {"rpe": float("-inf")},
        {"rpe": 0.0},
        {"rpe": 10.1},
        {"completed": True},
        {"unknown": "rejected"},
    ],
)
def test_rejects_invalid_measurements(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        WorkoutSet.model_validate({"number": 1, "completed": False, **change})


def test_duration_zero_weight_and_unknown_are_distinct() -> None:
    timed = WorkoutSet(number=1, duration_seconds=30, weight_kg=0.0, completed=True)
    assert timed.weight_kg == 0.0
    assert WorkoutSet(number=1, reps=8, completed=True).weight_kg is None
    with pytest.raises(ValidationError, match="not both"):
        WorkoutSet(number=1, reps=8, duration_seconds=30, completed=True)


@pytest.mark.parametrize("field", ["reps", "duration_seconds", "weight_kg", "rpe"])
def test_skipped_exercise_rejects_measurements(field: str) -> None:
    with pytest.raises(ValidationError, match="Skipped"):
        WorkoutExercise.model_validate({
            "position": 0,
            "skipped": True,
            "sets": [{"number": 1, "completed": False, field: 1}],
        })


def test_skipped_completed_and_duplicate_sets_rejected() -> None:
    with pytest.raises(ValidationError, match="Skipped"):
        WorkoutExercise(
            position=0, skipped=True, sets=[WorkoutSet(number=1, reps=8, completed=True)]
        )
    with pytest.raises(ValidationError, match="unique"):
        WorkoutExercise(
            position=0,
            skipped=False,
            sets=[WorkoutSet(number=1, completed=False), WorkoutSet(number=1, completed=False)],
        )


@pytest.mark.parametrize("positions", [[1], [0, 0], [0, 1]])
def test_prescription_positions_must_match_exactly(positions: list[int]) -> None:
    entries = [actual().model_copy(update={"position": index}) for index in positions]
    with pytest.raises(WorkoutValidationError, match="prescribed exercise"):
        UpdateWorkout(revision=0, status="in_progress", exercises=entries).validate_prescription(
            prescription()
        )


@pytest.mark.parametrize("numbers", [[1, 2], [1, 2, 4], [1, 2, 3, 4]])
def test_prescription_requires_exact_set_numbers(numbers: list[int]) -> None:
    entry = WorkoutExercise(
        position=0, skipped=False, sets=[WorkoutSet(number=n, completed=False) for n in numbers]
    )
    with pytest.raises(WorkoutValidationError, match="set numbers"):
        UpdateWorkout(revision=0, status="in_progress", exercises=[entry]).validate_prescription(
            prescription()
        )


def test_completion_requires_all_sets_and_real_performance() -> None:
    patch = UpdateWorkout(revision=0, status="completed", exercises=[actual(completed=False)])
    with pytest.raises(WorkoutValidationError, match="every prescribed set"):
        patch.validate_prescription(prescription())
    patch.exercises[0].skipped = True
    with pytest.raises(WorkoutValidationError, match="performed set"):
        patch.validate_prescription(prescription())
    patch.status = "in_progress"
    patch.validate_prescription(prescription())


def test_partial_completion_allowed_with_skipped_exercises() -> None:
    day = prescription().model_copy(deep=True)
    day.exercises.append(day.exercises[0].model_copy())
    skipped = actual(completed=False)
    skipped.position = 1
    skipped.skipped = True
    UpdateWorkout(
        revision=0, status="completed", exercises=[skipped, actual()]
    ).validate_prescription(day)


def test_start_accepts_uuid_but_not_arbitrary_ids() -> None:
    request_id = str(uuid4())
    assert (
        str(
            StartWorkout.model_validate({
                "request_id": request_id,
                "plan_id": 1,
                "week": 1,
                "day": 1,
            }).request_id
        )
        == request_id
    )
    with pytest.raises(ValidationError):
        StartWorkout.model_validate({"request_id": "bad", "plan_id": 1, "week": 1, "day": 1})


@pytest.mark.asyncio
async def test_bootstrap_returns_current_prescription_and_unknown_calendar() -> None:
    conversation = AsyncMock()
    training = AsyncMock()
    training.get_cycle.return_value = None
    conversation.get_current_plan.return_value = StoredTrainingPlan(
        id=42, version=3, plan=TrainingPlan.model_validate(build_plan_payload()), report="report"
    )
    service = WorkoutService(AsyncMock(), conversation, training)
    result = await service.bootstrap(123)
    assert (result.plan_id, result.version, result.current_week) == (42, 3, None)
    assert result.cycle is None
    conversation.get_current_plan.assert_awaited_once_with(123)
    conversation.get_current_plan.return_value = None
    with pytest.raises(WorkoutNotFoundError, match="No current"):
        await service.bootstrap(123)


@pytest.mark.asyncio
async def test_progress_only_compares_repetition_sets_with_known_measurements() -> None:
    repository = AsyncMock()
    first = workout()
    first.exercises[0].sets[0].weight_kg = 0.0
    first.exercises[0].sets[0].rpe = 7.0
    second = workout(session_id=2)
    second.exercises[0].sets = [
        WorkoutSet(number=1, duration_seconds=30, weight_kg=100.0, completed=True),
        WorkoutSet(number=2, reps=10, completed=True),
        WorkoutSet(number=3, reps=12, rpe=9.0, completed=True),
    ]
    second.prescription.exercises[0].name = "New label"
    repository.list_sessions.return_value = [second, first]
    repository.completed_count.return_value = 22
    result = await WorkoutService(repository, AsyncMock(), AsyncMock()).progress(123)
    assert result.completed_sessions == 22
    assert result.history_limit == 100
    assert result.history_truncated is True
    assert len(result.exercises) == 1
    progress = result.exercises[0]
    assert progress.name == "New label"
    assert [entry.session_id for entry in progress.history] == [1, 2]
    assert progress.history[0].max_weight_kg == 0.0
    assert progress.history[1].max_weight_kg is None
    assert progress.history[1].total_sets == 3
    assert progress.history[1].total_reps == 22
    assert progress.history[1].total_duration_seconds == 30
    assert progress.history[1].average_rpe == 9.0
    repository.list_sessions.assert_awaited_once_with(123, completed_only=True)


@pytest.mark.asyncio
async def test_progress_reports_time_only_sets_without_inventing_repetitions() -> None:
    repository = AsyncMock()
    session = workout()
    session.exercises[0].sets = [WorkoutSet(number=1, duration_seconds=60, completed=True)]
    repository.list_sessions.return_value = [session]
    repository.completed_count.return_value = 1
    result = await WorkoutService(repository, AsyncMock(), AsyncMock()).progress(123)
    assert result.completed_sessions == 1
    assert result.exercises[0].history[0].total_reps is None
    assert result.exercises[0].history[0].total_duration_seconds == 60
    assert result.exercises[0].history[0].total_sets == 1
    assert result.history_truncated is False


@pytest.mark.asyncio
async def test_renewal_summary_is_bounded_and_keeps_only_performed_sets() -> None:
    repository = PostgresWorkoutRepository(AsyncMock())
    session = workout()
    for position in range(1, 100):
        session.prescription.exercises.append(session.prescription.exercises[0].model_copy())
        session.exercises.append(actual().model_copy(update={"position": position}, deep=True))
    session.exercises[0].sets[0] = WorkoutSet(
        number=1, duration_seconds=30, weight_kg=0.0, completed=True
    )
    # An incomplete stored draft measurement must never become renewal performance.
    session.exercises[0].sets[1] = WorkoutSet(number=2, reps=50, completed=False)
    sessions = [session.model_copy(update={"id": index}, deep=True) for index in range(100, 0, -1)]
    with patch.object(repository, "list_sessions", AsyncMock(return_value=sessions)) as listing:
        result = await repository.performance_summary(123, 9)
    listing.assert_awaited_once_with(123, completed_only=True, mesocycle_id=9)
    assert len(result["completed_slots"]) == 28
    assert len(result["measurements"]) == 100
    assert result["truncated"] is True
    first = result["measurements"][0]["sets"]
    assert len(first) == 2
    assert first[0]["duration_seconds"] == 30
    assert first[0]["reps"] is None
    assert first[0]["weight_kg"] == 0.0
    assert first[1]["weight_kg"] is None
    assert result["recorded_sets"] == 29900
    assert result["duration_sets"] == 100
    assert result["repetition_sets"] == 29800
    assert result["coverage"]["unknown_weight_sets"] == 29800
    assert result["coverage"]["prescribed_sets_in_completed_sessions"] == 30000
    assert result["units"]["duration_seconds"] == "seconds"
    assert "prescription" not in result
