"""Deterministic plan checks: each rule fires on the plan that breaks it, and only then."""

from dataclasses import replace
from typing import Any

import pytest

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainerTurn, TrainingPlan
from fitcoach.service.agent.plan_evaluator import (
    PlanEvaluation,
    Severity,
    evaluate_plan,
    evaluate_turn,
)

INTENSITIES = ("accumulation", "intensification", "peak", "deload")
# A periodization the skill accepts: W2 harder, W3 more volume, W4 at ~67% of W1.
GOOD_WEEKS = ((3, 7.0), (3, 7.5), (4, 8.0), (2, 6.0))


def exercise_payload(exercise_id: int, name: str, sets: int, rpe: float) -> dict[str, Any]:
    return {
        "exercise_id": exercise_id,
        "name": name,
        "sets": sets,
        "reps": "8-10",
        "rest_seconds": 120,
        "rpe": rpe,
        "notes": None,
    }


def plan_payload(
    weeks: tuple[tuple[int, float], ...] = GOOD_WEEKS, days: int = 3, **overrides: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "goal": "gain_muscle",
        "days_per_week": days,
        "environment": "gym",
        "weeks": [
            {
                "week": index,
                "intensity": INTENSITIES[index - 1],
                "days": [
                    {
                        "day": day,
                        "focus": "Full body",
                        "estimated_minutes": 45,
                        "exercises": [
                            exercise_payload(101, "barbell bench press", sets, rpe),
                            exercise_payload(102, "barbell row", sets, rpe),
                        ],
                    }
                    for day in range(1, days + 1)
                ],
            }
            for index, (sets, rpe) in enumerate(weeks, start=1)
        ],
        "excluded_by_injury": [],
        "progression_notes": "Sube 2,5 kg al completar el rango alto.",
    }
    payload.update(overrides)
    return payload


def build_plan(payload: dict[str, Any]) -> TrainingPlan:
    return TrainingPlan.model_validate(payload)


def edit_profile(profile: InterviewerProfile, **sections: dict[str, Any]) -> InterviewerProfile:
    data = profile.model_dump()
    for section, values in sections.items():
        data[section] = {**data[section], **values}
    return InterviewerProfile.model_validate(data)


def with_injury(profile: InterviewerProfile, location: str) -> InterviewerProfile:
    data = profile.model_dump()
    data["injuries"] = [
        {"location": location, "type": "dolor", "age": "1 año", "restriction": "evitar impacto"}
    ]
    return InterviewerProfile.model_validate(data)


def rules(evaluation: PlanEvaluation, severity: Severity | None = None) -> set[str]:
    return {
        finding.rule
        for finding in evaluation.findings
        if severity is None or finding.severity is severity
    }


def evaluate(
    payload: dict[str, Any], profile: InterviewerProfile, catalogue: list[Exercise]
) -> PlanEvaluation:
    return evaluate_plan(build_plan(payload), profile, catalogue)


def mutate_exercise(payload: dict[str, Any], week: int, **values: Any) -> dict[str, Any]:
    for day in payload["weeks"][week - 1]["days"]:
        day["exercises"][0].update(values)
    return payload


class TestCleanPlan:
    def test_well_formed_plan_has_no_errors_or_warnings(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        evaluation = evaluate(plan_payload(), profile, exercises)

        assert rules(evaluation, Severity.ERROR) == set()
        assert rules(evaluation, Severity.WARNING) == set()
        assert evaluation.passed
        assert evaluation.score == 100

    def test_missing_catalogue_group_is_only_informative(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        evaluation = evaluate(plan_payload(), profile, exercises)

        assert {"catalogue_missing_group", "group_not_trained"} <= rules(evaluation, Severity.INFO)

    def test_metrics_describe_the_plan(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        metrics = evaluate(plan_payload(), profile, exercises).metrics

        assert metrics["weekly_sets"] == [18, 18, 24, 12]
        assert metrics["mean_rpe"] == [7.0, 7.5, 8.0, 6.0]
        assert metrics["week1_sets_per_target"] == {"lats": 9, "pectorals": 9}
        assert metrics["distinct_exercises"] == 2
        assert metrics["exercises_per_day"] == 2.0
        assert metrics["max_estimated_minutes"] == 45
        assert metrics["max_formula_minutes"] == 34

    def test_to_dict_is_serializable_summary(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        data = evaluate(plan_payload(), profile, exercises).to_dict()

        assert data["score"] == 100
        assert data["passed"] is True
        assert data["errors"] == 0
        assert data["findings"][0].keys() == {"rule", "severity", "message", "where"}


class TestErrors:
    def test_profile_mismatch(self, profile: InterviewerProfile, exercises: list[Exercise]) -> None:
        evaluation = evaluate(plan_payload(environment="home"), profile, exercises)

        assert "profile_mismatch" in rules(evaluation, Severity.ERROR)

    def test_unknown_id_and_name_mismatch(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload()
        payload["weeks"][0]["days"][0]["exercises"][0]["exercise_id"] = 999
        payload["weeks"][0]["days"][1]["exercises"][0]["name"] = "dumbbell fly"

        found = rules(evaluate(payload, profile, exercises), Severity.ERROR)

        assert {"unknown_exercise_id", "name_mismatch"} <= found

    def test_session_over_budget(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload()
        payload["weeks"][0]["days"][0]["estimated_minutes"] = 75

        assert "session_over_budget" in rules(evaluate(payload, profile, exercises))

    def test_duplicate_exercise_in_day(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload()
        payload["weeks"][0]["days"][0]["exercises"][1]["exercise_id"] = 101
        payload["weeks"][0]["days"][0]["exercises"][1]["name"] = "barbell bench press"

        assert "duplicate_exercise_in_day" in rules(evaluate(payload, profile, exercises))

    def test_volume_over_ceiling_counts_sets_per_target(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        # 3 days x 5 sets = 15 sets per muscle in week 1, above the profile's 12.
        payload = plan_payload(weeks=((5, 7.0), (5, 7.5), (6, 8.0), (3, 6.0)))

        found = evaluate(payload, profile, exercises).findings

        assert {f.where for f in found if f.rule == "volume_over_ceiling"} == {"W1"}

    def test_volume_ceiling_applies_to_every_week_with_red_flags(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        flagged = edit_profile(profile, flags={"red": ["dolor torácico"]})
        payload = plan_payload(weeks=((3, 7.0), (3, 7.5), (5, 8.0), (2, 6.0)))

        found = evaluate(payload, flagged, exercises).findings

        assert {f.where for f in found if f.rule == "volume_over_ceiling"} == {"W3"}

    def test_deload_with_as_much_volume_as_week_one(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload(weeks=((3, 7.0), (3, 7.5), (4, 8.0), (3, 6.0)))

        assert "deload_volume" in rules(evaluate(payload, profile, exercises), Severity.ERROR)

    @pytest.mark.parametrize(("week", "rpe"), [(1, 8.5), (3, 9.5), (4, 7.0)])
    def test_rpe_over_cap(
        self, profile: InterviewerProfile, exercises: list[Exercise], week: int, rpe: float
    ) -> None:
        payload = mutate_exercise(plan_payload(), week, rpe=rpe)

        found = evaluate(payload, profile, exercises).findings

        assert any(f.rule == "rpe_over_cap" and f.where == f"W{week}" for f in found)

    def test_injury_not_recorded(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        injured = with_injury(profile, "codo")

        assert "injury_not_recorded" in rules(evaluate(plan_payload(), injured, exercises))

    def test_red_flags_forbid_maximal_effort(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        flagged = edit_profile(profile, flags={"red": ["hipertensión"]})
        payload = mutate_exercise(plan_payload(), 3, rpe=9.0)

        assert "red_flags_maximal_effort" in rules(evaluate(payload, flagged, exercises))


class TestWarnings:
    def test_flat_weeks_have_no_progression(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload(weeks=((3, 7.0), (3, 7.0), (3, 7.0), (2, 6.0)))

        found = evaluate(payload, profile, exercises).findings

        assert {f.where for f in found if f.rule == "no_progression"} == {"W2", "W3"}

    def test_deload_outside_range_is_a_warning(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload(weeks=((5, 7.0), (5, 7.5), (6, 8.0), (1, 6.0)))
        flexible = edit_profile(profile, initial_calculations={"tolerable_volume_sets": 20})

        assert "deload_volume" in rules(evaluate(payload, flexible, exercises), Severity.WARNING)

    def test_session_time_formula_over_budget(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = mutate_exercise(plan_payload(), 1, sets=10, rest_seconds=300)
        flexible = edit_profile(profile, initial_calculations={"tolerable_volume_sets": 40})

        assert "session_time_formula_over_budget" in rules(
            evaluate(payload, flexible, exercises), Severity.WARNING
        )

    def test_reps_and_rest_outside_goal_range(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = mutate_exercise(plan_payload(), 1, reps="20-25", rest_seconds=30)

        found = rules(evaluate(payload, profile, exercises), Severity.WARNING)

        assert {"reps_outside_goal_range", "rest_outside_goal_range"} <= found

    def test_timed_reps_are_not_checked_against_rep_ranges(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = mutate_exercise(plan_payload(), 1, reps="30 s")

        assert "reps_outside_goal_range" not in rules(evaluate(payload, profile, exercises))

    def test_exercises_change_between_weeks(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload()
        for offset, exercise in enumerate(payload["weeks"][1]["days"][0]["exercises"]):
            exercise.update(exercise_id=103 + offset, name=f"press {offset}")
        catalogue = [
            *exercises,
            replace(exercises[0], id=103, name="press 0"),
            replace(exercises[1], id=104, name="press 1"),
        ]

        assert "exercises_change_between_weeks" in rules(evaluate(payload, profile, catalogue))

    def test_group_available_but_not_trained(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        squat = replace(exercises[0], id=103, name="squat", target="quads")

        found = evaluate(plan_payload(), profile, [*exercises, squat]).findings

        assert any(
            f.rule == "group_not_trained" and f.severity is Severity.WARNING and "legs" in f.message
            for f in found
        )

    def test_phantom_injury_exclusion(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        payload = plan_payload(excluded_by_injury=["sentadilla"])

        assert "phantom_injury_exclusion" in rules(evaluate(payload, profile, exercises))

    def test_possible_injury_conflict(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        injured = with_injury(profile, "rodilla derecha")
        squat = replace(exercises[0], id=103, name="barbell squat")
        payload = plan_payload(excluded_by_injury=["saltos"])
        for week in payload["weeks"]:
            week["days"][0]["exercises"][0].update(exercise_id=103, name="barbell squat")

        found = rules(evaluate(payload, injured, [*exercises, squat]))

        assert "possible_injury_conflict" in found
        assert "injury_not_recorded" not in found


class TestTurn:
    def turn(self, payload: dict[str, Any], report: str = "Tu plan.", reply: str = "Listo") -> Any:
        return TrainerTurn.model_validate({
            "status": "plan",
            "reply": reply,
            "report": report,
            "plan": payload,
        })

    def test_answer_turn_is_an_error(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        turn = TrainerTurn.model_validate({"status": "answer", "reply": "Hola"})

        evaluation = evaluate_turn(turn, profile, exercises)

        assert rules(evaluation, Severity.ERROR) == {"no_plan"}
        assert evaluation.score == 85

    def test_long_messages(self, profile: InterviewerProfile, exercises: list[Exercise]) -> None:
        turn = self.turn(plan_payload(), report="x" * 4097, reply="y" * 601)

        found = rules(evaluate_turn(turn, profile, exercises))

        assert {"report_over_telegram_limit", "reply_too_long"} <= found

    def test_red_flags_require_a_referral(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        flagged = edit_profile(profile, flags={"red": ["dolor torácico"]})

        silent = evaluate_turn(self.turn(plan_payload()), flagged, exercises)
        referred = evaluate_turn(
            self.turn(plan_payload(), report="Consulta con tu médico antes de empezar."),
            flagged,
            exercises,
        )

        assert "red_flags_no_referral" in rules(silent)
        assert "red_flags_no_referral" not in rules(referred)

    def test_clean_turn_scores_full_marks(
        self, profile: InterviewerProfile, exercises: list[Exercise]
    ) -> None:
        evaluation = evaluate_turn(self.turn(plan_payload()), profile, exercises)

        assert evaluation.score == 100
        assert evaluation.metrics["catalogue_size"] == 2
