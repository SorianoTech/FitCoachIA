import pytest
from pydantic import ValidationError

from fitcoach.domain.exercise_submission import ExerciseProposal


def proposal(**overrides: object) -> ExerciseProposal:
    values: dict[str, object] = {
        "name": "Backpack row",
        "category": "back",
        "body_part": "back",
        "equipment": "body weight",
        "target": "lats",
        "secondary_muscles": ["biceps"],
        "instructions_en": "Hold the backpack, hinge at the hips, and row it toward the torso.",
    }
    values.update(overrides)
    return ExerciseProposal.model_validate(values)


def test_normalizes_catalogue_fields_and_derives_group() -> None:
    result = proposal(equipment="Mancuerna", target="LATS", secondary_muscles=["Biceps"])

    assert result.equipment == "dumbbell"
    assert result.target == "lats"
    assert result.secondary_muscles == ["biceps"]
    assert result.muscle_group == "back"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("equipment", "backpack"),
        ("target", "rhomboids"),
        ("secondary_muscles", ["biceps", "BICEPS"]),
    ],
)
def test_rejects_values_that_cannot_enter_the_catalogue(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        proposal(**{field: value})
