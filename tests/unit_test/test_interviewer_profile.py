from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from fitcoach.domain.interviewer_profile import InterviewerTurn


def _profile() -> dict[str, object]:
    return {
        "user": {"name_or_username": "Ana", "registration_date": datetime.now(UTC)},
        "biometrics": {
            "age": 30,
            "weight_kg": 65.0,
            "height_cm": 170,
            "bmi": 22.5,
            "perceived_composition": "Poca grasa",
            "estimated_composition": "No evaluada",
        },
        "goal": {"primary": "gain_muscle", "timeframe_weeks": 12, "realistic_expectation": True},
        "activity": {
            "occupation": "Oficina",
            "neat_level": "sedentary",
            "description": "Camino poco",
        },
        "nutrition": {"meals_per_day": 3, "critical_foods": [], "general_pattern": "Mediterránea"},
        "digestive_energy": {"bloating_frequency": "never", "energy_crash": False, "triggers": []},
        "injuries": [],
        "training": {"consistent_years": 1.0, "environment": "gym", "equipment": ["mancuernas"]},
        "sleep": {"average_hours": 7.5, "quality": "good", "problems": []},
        "supplementation": {"current": [], "monthly_budget_usd": None, "restrictions": []},
        "commitment": {
            "days_per_week": 3,
            "minutes_per_session": 60,
            "flexibility": "fixed",
        },
        "flags": {"red": [], "yellow": []},
        "initial_calculations": {
            "bmr": 1400.0,
            "estimated_tdee": 1900.0,
            "tolerable_volume_sets": 12,
        },
    }


def test_completed_turn_requires_a_valid_profile_and_report() -> None:
    turn = InterviewerTurn(
        status="completed",
        reply="He terminado la entrevista.",
        report="Resumen de Ana",
        profile=_profile(),
    )

    assert turn.profile is not None
    assert turn.profile.user.name_or_username == "Ana"


def test_in_progress_turn_cannot_contain_a_profile() -> None:
    with pytest.raises(ValidationError, match="in-progress"):
        InterviewerTurn(status="in_progress", reply="¿Cuánto pesas?", profile=_profile())


def test_completed_turn_requires_a_report() -> None:
    with pytest.raises(ValidationError, match="completed interview"):
        InterviewerTurn(status="completed", reply="He terminado.", profile=_profile())
