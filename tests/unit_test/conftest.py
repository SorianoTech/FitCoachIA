"""Fixtures shared by the trainer tests: a valid profile and a valid plan payload."""

from datetime import UTC, datetime

import pytest

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile

_INTENSITIES = ("accumulation", "intensification", "peak", "deload")


@pytest.fixture
def profile() -> InterviewerProfile:
    return InterviewerProfile.model_validate({
        "user": {"name_or_username": "Ana", "registration_date": datetime.now(UTC)},
        "biometrics": {
            "age": 30,
            "weight_kg": 70.0,
            "height_cm": 170,
            "bmi": 24.2,
            "perceived_composition": "algo de grasa",
            "estimated_composition": "normal",
        },
        "goal": {
            "primary": "gain_muscle",
            "secondary": None,
            "timeframe_weeks": 12,
            "realistic_expectation": True,
        },
        "activity": {
            "occupation": "oficina",
            "neat_level": "sedentary",
            "description": "ocho horas sentada",
        },
        "nutrition": {"meals_per_day": 3, "critical_foods": [], "general_pattern": "variada"},
        "digestive_energy": {
            "bloating_frequency": "never",
            "energy_crash": False,
            "triggers": [],
        },
        "injuries": [],
        "training": {"consistent_years": 1.0, "environment": "gym", "equipment": ["barbell"]},
        "sleep": {"average_hours": 7.0, "quality": "good", "problems": []},
        "supplementation": {"current": [], "monthly_budget_usd": None, "restrictions": []},
        "commitment": {
            "days_per_week": 3,
            "minutes_per_session": 60,
            "flexibility": "flexible",
            "dropout_history": None,
        },
        "flags": {"red": [], "yellow": []},
        "initial_calculations": {
            "bmr": 1450.0,
            "estimated_tdee": 2000.0,
            "tolerable_volume_sets": 12,
        },
    })


@pytest.fixture
def exercises() -> list[Exercise]:
    return [
        Exercise(
            id=101,
            name="barbell bench press",
            category="strength",
            body_part="chest",
            equipment="barbell",
            muscle_group="chest",
            target="pectorals",
            secondary_muscles=["triceps"],
            instructions_en="Lie on the bench and press.",
        ),
        Exercise(
            id=102,
            name="barbell row",
            category="strength",
            body_part="back",
            equipment="barbell",
            muscle_group="back",
            target="lats",
            secondary_muscles=["biceps"],
            instructions_en="Hinge and row.",
        ),
    ]


def build_plan_payload(
    exercise_id: int = 101, days_per_week: int = 3, **overrides: object
) -> dict[str, object]:
    """A schema-valid plan, so tests can vary just the part they care about."""
    payload: dict[str, object] = {
        "goal": "gain_muscle",
        "days_per_week": days_per_week,
        "environment": "gym",
        "weeks": [
            {
                "week": week,
                "intensity": _INTENSITIES[week - 1],
                "days": [
                    {
                        "day": day,
                        "focus": "Full body",
                        "estimated_minutes": 55,
                        "exercises": [
                            {
                                "exercise_id": exercise_id,
                                "name": "barbell bench press",
                                "sets": 3,
                                "reps": "8-10",
                                "rest_seconds": 120,
                                "rpe": 7.0,
                                "notes": None,
                            }
                        ],
                    }
                    for day in range(1, days_per_week + 1)
                ],
            }
            for week in range(1, 5)
        ],
        "excluded_by_injury": [],
        "progression_notes": "Sube 2,5 kg al completar el rango alto.",
    }
    payload.update(overrides)
    return payload
