import pytest
from pydantic import ValidationError

from fitcoach.domain.trainer_plan import TrainerTurn, TrainingPlan

_INTENSITIES = ["accumulation", "intensification", "peak", "deload"]


def _exercise(exercise_id: int = 1) -> dict[str, object]:
    return {
        "exercise_id": exercise_id,
        "name": "push up",
        "sets": 3,
        "reps": "8-10",
        "rest_seconds": 90,
        "rpe": 7.0,
        "notes": None,
    }


def _day(day: int = 1, exercise_ids: tuple[int, ...] = (1,)) -> dict[str, object]:
    return {
        "day": day,
        "focus": "Full body",
        "exercises": [_exercise(exercise_id) for exercise_id in exercise_ids],
        "estimated_minutes": 45,
    }


def _plan(days_per_week: int = 1, weeks: int = 4, **overrides: object) -> dict[str, object]:
    plan: dict[str, object] = {
        "goal": "gain_muscle",
        "days_per_week": days_per_week,
        "environment": "gym",
        "weeks": [
            {
                "week": week,
                "intensity": _INTENSITIES[(week - 1) % len(_INTENSITIES)],
                "days": [_day(day) for day in range(1, days_per_week + 1)],
            }
            for week in range(1, weeks + 1)
        ],
        "excluded_by_injury": [],
        "progression_notes": "Sube 2,5 kg cuando completes el rango alto.",
    }
    plan.update(overrides)
    return plan


class TestTrainingPlan:
    def test_accepts_a_well_formed_four_week_mesocycle(self) -> None:
        plan = TrainingPlan.model_validate(_plan(days_per_week=3))

        assert len(plan.weeks) == 4
        assert [week.week for week in plan.weeks] == [1, 2, 3, 4]
        assert all(len(week.days) == 3 for week in plan.weeks)

    def test_rejects_a_mesocycle_shorter_than_four_weeks(self) -> None:
        with pytest.raises(ValidationError, match="weeks 1..4"):
            TrainingPlan.model_validate(_plan(weeks=3))

    def test_rejects_a_mesocycle_longer_than_four_weeks(self) -> None:
        # Caught by the per-field bound (week <= 4) before the model validator runs.
        with pytest.raises(ValidationError, match="less than or equal to 4"):
            TrainingPlan.model_validate(_plan(weeks=5))

    def test_rejects_weeks_that_are_out_of_order(self) -> None:
        payload = _plan()
        payload["weeks"] = list(reversed(payload["weeks"]))  # type: ignore[arg-type]

        with pytest.raises(ValidationError, match="weeks 1..4"):
            TrainingPlan.model_validate(payload)

    def test_rejects_a_week_with_fewer_days_than_committed(self) -> None:
        payload = _plan(days_per_week=3)
        payload["weeks"][0]["days"] = [_day(1)]  # type: ignore[index]

        with pytest.raises(ValidationError, match="committed to 3"):
            TrainingPlan.model_validate(payload)

    def test_rejects_a_week_that_repeats_a_day(self) -> None:
        payload = _plan(days_per_week=2)
        payload["weeks"][0]["days"] = [_day(1), _day(1)]  # type: ignore[index]

        with pytest.raises(ValidationError, match="repeats a day"):
            TrainingPlan.model_validate(payload)

    def test_rejects_an_unknown_intensity_value(self) -> None:
        payload = _plan()
        payload["weeks"][0]["intensity"] = "very hard"  # type: ignore[index]

        with pytest.raises(ValidationError):
            TrainingPlan.model_validate(payload)

    def test_rejects_an_unknown_goal_value(self) -> None:
        with pytest.raises(ValidationError):
            TrainingPlan.model_validate(_plan(goal="get_shredded"))

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            TrainingPlan.model_validate(_plan(coach_notes="hola"))

    def test_exercise_ids_collects_every_id_in_the_plan(self) -> None:
        payload = _plan(days_per_week=2)
        payload["weeks"][0]["days"] = [_day(1, (10, 11)), _day(2, (12,))]  # type: ignore[index]

        plan = TrainingPlan.model_validate(payload)

        assert {10, 11, 12} <= plan.exercise_ids()


class TestTrainerTurn:
    def test_plan_turn_requires_report_and_plan(self) -> None:
        turn = TrainerTurn.model_validate({
            "status": "plan",
            "reply": "Listo",
            "report": "Tu plan de 4 semanas",
            "plan": _plan(),
        })

        assert turn.plan is not None
        assert turn.report == "Tu plan de 4 semanas"

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "plan", "reply": "Listo"},
            {"status": "plan", "reply": "Listo", "report": "resumen"},
            {"status": "plan", "reply": "Listo", "plan": _plan()},
        ],
    )
    def test_rejects_a_plan_turn_missing_report_or_plan(self, payload: dict[str, object]) -> None:
        with pytest.raises(ValidationError, match="requires both report and plan"):
            TrainerTurn.model_validate(payload)

    def test_answer_turn_carries_only_a_reply(self) -> None:
        turn = TrainerTurn.model_validate({"status": "answer", "reply": "Porque progresas mejor"})

        assert turn.plan is None
        assert turn.report is None

    @pytest.mark.parametrize(
        "extra",
        [{"report": "resumen"}, {"plan": _plan()}],
    )
    def test_rejects_an_answer_turn_carrying_a_plan(self, extra: dict[str, object]) -> None:
        with pytest.raises(ValidationError, match="cannot include report or plan"):
            TrainerTurn.model_validate({"status": "answer", "reply": "hola", **extra})

    def test_rejects_an_empty_reply(self) -> None:
        with pytest.raises(ValidationError):
            TrainerTurn.model_validate({"status": "answer", "reply": ""})
