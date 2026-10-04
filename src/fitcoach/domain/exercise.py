"""An exercise retrieved from the vector database.

Plain dataclass, not a Pydantic model: these rows are read-only reference data
coming from a trusted corpus, and they never cross the application boundary as
user input.
"""

from dataclasses import dataclass, field
from math import isfinite


@dataclass(frozen=True, slots=True)
class Exercise:
    id: int
    name: str
    category: str | None = None
    body_part: str | None = None
    equipment: str | None = None
    muscle_group: str | None = None
    target: str | None = None
    secondary_muscles: list[str] = field(default_factory=list)
    instructions_en: str | None = None


@dataclass(frozen=True, slots=True)
class ExerciseMatch:
    exercise: Exercise
    distance: float

    def __post_init__(self) -> None:
        if not isfinite(self.distance) or not 0 <= self.distance <= 2:
            raise ValueError("Cosine distance must be finite and between 0 and 2")

    @property
    def similarity(self) -> float:
        return 1 - self.distance
