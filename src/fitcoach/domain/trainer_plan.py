"""Strict contract for the Trainer's output, mirroring ``interviewer_profile``.

The model returns exactly one JSON object per turn. Anything the schema does not
allow is rejected here rather than handed to the user, so a hallucinated plan
never reaches Telegram or the database.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MESOCYCLE_WEEKS = 4
RPE_CAPS = {1: 8.0, 3: 9.0, 4: 6.0}

# Estado de training_sessions: hay un plan vigente y el entrenador responde preguntas.
TRAINING_STATUS_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class TrainerGenerationTrace:
    """Identifiers needed to reproduce which Trainer inputs generated a plan."""

    model: str
    skill_name: str
    prompt_hash: str
    skill_hash: str
    retrieved_exercise_ids: tuple[int, ...]


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlannedExercise(PlanModel):
    # Logical FK to exercises.id in the vector database. Validated against the
    # retrieved set by TrainerChain; Pydantic alone cannot know what was retrieved.
    exercise_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    sets: int = Field(ge=1, le=10)
    reps: str = Field(min_length=1)
    rest_seconds: int = Field(ge=15, le=600)
    rpe: float | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class TrainingDay(PlanModel):
    day: int = Field(ge=1, le=7)
    focus: str = Field(min_length=1)
    exercises: list[PlannedExercise] = Field(min_length=1)
    estimated_minutes: int = Field(ge=15, le=180)


class TrainingWeek(PlanModel):
    week: int = Field(ge=1, le=MESOCYCLE_WEEKS)
    intensity: Literal["accumulation", "intensification", "peak", "deload"]
    days: list[TrainingDay] = Field(min_length=1)


class TrainingPlan(PlanModel):
    goal: Literal["lose_fat", "gain_muscle", "performance"]
    days_per_week: int = Field(ge=1, le=7)
    environment: Literal["gym", "home", "outdoors", "mixed"]
    # Also exported as minItems/maxItems, so strict structured outputs cannot cut it short.
    weeks: list[TrainingWeek] = Field(min_length=MESOCYCLE_WEEKS, max_length=MESOCYCLE_WEEKS)
    excluded_by_injury: list[str]
    progression_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_mesocycle(self) -> "TrainingPlan":
        weeks = [week.week for week in self.weeks]
        if weeks != list(range(1, MESOCYCLE_WEEKS + 1)):
            raise ValueError(f"A mesocycle needs weeks 1..{MESOCYCLE_WEEKS} in order, got {weeks}")
        intensities = [week.intensity for week in self.weeks]
        expected_intensities = ["accumulation", "intensification", "peak", "deload"]
        if intensities != expected_intensities:
            raise ValueError(
                f"A mesocycle needs intensities {expected_intensities}, got {intensities}"
            )
        for week in self.weeks:
            if len(week.days) != self.days_per_week:
                raise ValueError(
                    f"Week {week.week} has {len(week.days)} days "
                    f"but the client committed to {self.days_per_week}"
                )
            days = [day.day for day in week.days]
            if len(set(days)) != len(days):
                raise ValueError(f"Week {week.week} repeats a day: {days}")
        return self

    def exercise_ids(self) -> set[int]:
        return {
            exercise.exercise_id
            for week in self.weeks
            for day in week.days
            for exercise in day.exercises
        }


class TrainerAction(StrEnum):
    """Que hizo el entrenador en un turno. Los valores son los de ``TrainerTurn.status``."""

    GENERATE_PLAN = "plan"
    ANSWER_PLAN = "answer"


class TrainerTurn(PlanModel):
    """``plan`` delivers a new mesocycle; ``answer`` is a follow-up reply."""

    # strict=False only for the enum: in strict mode Pydantic rejects "plan"/"answer"
    # from a dict (only JSON input coerces). The value set is still enforced.
    status: TrainerAction = Field(strict=False)
    reply: str = Field(min_length=1)
    report: str | None = None
    plan: TrainingPlan | None = None
    intent: Literal["answer", "renewal", "exercise_swap"] = Field(default_factory=lambda: "answer")

    @model_validator(mode="after")
    def validate_completion(self) -> "TrainerTurn":
        if self.status == "plan" and (self.report is None or self.plan is None):
            raise ValueError("A plan turn requires both report and plan")
        if self.status == "answer" and (self.report is not None or self.plan is not None):
            raise ValueError("An answer turn cannot include report or plan")
        return self


class SwapSelection(PlanModel):
    week: int | None = Field(default=None, ge=1, le=4)
    exercise_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, min_length=1)


class TrainerAnswerTurn(TrainerTurn):
    """Read-only follow-up: never accepts a generated or modified plan."""

    status: Literal[TrainerAction.ANSWER_PLAN]
    report: None = None
    plan: None = None
    swap_selection: SwapSelection | None = Field(default_factory=lambda: None)
