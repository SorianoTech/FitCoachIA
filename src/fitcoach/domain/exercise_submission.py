"""Validated exercise proposals and their moderation lifecycle."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from fitcoach.domain.exercise_catalogue import (
    MUSCLE_TARGETS,
    canonical_group,
    known_equipment,
    normalize_equipment,
)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
InstructionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)
]
_KNOWN_TARGETS = frozenset(target for targets in MUSCLE_TARGETS.values() for target in targets)


class ExerciseSubmissionStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ExerciseProposal(BaseModel):
    """Canonical fields accepted by the existing exercise catalogue."""

    model_config = ConfigDict(extra="forbid")

    name: ShortText
    category: ShortText
    body_part: ShortText
    equipment: ShortText
    target: ShortText
    secondary_muscles: list[ShortText] = Field(max_length=8)
    instructions_en: InstructionText

    @field_validator("equipment")
    @classmethod
    def _known_equipment(cls, value: str) -> str:
        normalized = normalize_equipment(value)
        if normalized not in known_equipment():
            raise ValueError("Unknown equipment")
        return normalized

    @field_validator("target")
    @classmethod
    def _known_target(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in _KNOWN_TARGETS:
            raise ValueError("Unknown target")
        return normalized

    @field_validator("secondary_muscles")
    @classmethod
    def _unique_secondary_muscles(cls, values: list[str]) -> list[str]:
        normalized = [value.lower() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Secondary muscles must be unique")
        return normalized

    @property
    def muscle_group(self) -> str:
        group = canonical_group(self.target)
        if group is None:
            raise ValueError("Target has no canonical muscle group")
        return group


class ExerciseSubmission(BaseModel):
    """Persisted proposal, including provenance and moderation metadata."""

    model_config = ConfigDict(extra="forbid")

    id: int
    chat_id: int
    message_thread_id: int | None
    raw_description: str
    proposal: ExerciseProposal
    status: ExerciseSubmissionStatus
    model: str
    duplicate_exercise_id: int | None = None
    moderation_notes: str | None = None
    reviewed_by: int | None = None
    published_exercise_id: int | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
