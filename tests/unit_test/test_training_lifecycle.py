from datetime import UTC, datetime, timedelta

import pytest

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import PlannedExercise, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    Mesocycle,
    SwapRequest,
    TrainingProfilePatch,
    apply_swap,
    expected_end,
)
from tests.unit_test.conftest import build_plan_payload


def test_due_is_not_completion() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    cycle = Mesocycle(id=1, started_at=start, expected_end_at=expected_end(start))
    assert not cycle.due(start + timedelta(days=27))
    assert cycle.due(start + timedelta(days=28))
    assert cycle.completed_at is None


def test_legacy_dates_do_not_trigger_reminders() -> None:
    cycle = Mesocycle(id=1, started_at=None, expected_end_at=None)
    assert not cycle.due(datetime.now(UTC))


def test_swap_preserves_previous_weeks() -> None:
    plan = TrainingPlan.model_validate(build_plan_payload())
    replacement = PlannedExercise(
        exercise_id=202, name="press", sets=3, reps="8-10", rest_seconds=120
    )
    changed = apply_swap(
        plan, SwapRequest(exercise_id=101, from_week=3, reason="material"), replacement
    )
    assert changed.weeks[0] == plan.weeks[0]
    assert changed.weeks[2].days[0].exercises[0].exercise_id == 202
    assert plan.weeks[2].days[0].exercises[0].exercise_id == 101


def test_swap_without_pending_occurrence_is_rejected() -> None:
    plan = TrainingPlan.model_validate(build_plan_payload())
    with pytest.raises(ValueError, match="No pending"):
        apply_swap(
            plan,
            SwapRequest(exercise_id=999, from_week=1, reason="preferencia"),
            plan.weeks[0].days[0].exercises[0],
        )


def test_profile_patch_preserves_non_training_data(profile: InterviewerProfile) -> None:
    patched = TrainingProfilePatch(
        sleep=profile.sleep.model_copy(update={"average_hours": 8.0})
    ).apply(profile)
    assert patched.sleep.average_hours == 8
    assert patched.biometrics == profile.biometrics
    assert patched.user == profile.user
