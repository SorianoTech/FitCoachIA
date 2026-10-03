"""An exercise retrieved from the vector database.

Plain dataclass, not a Pydantic model: these rows are read-only reference data
coming from a trusted corpus, and they never cross the application boundary as
user input.
"""

from dataclasses import dataclass, field


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
