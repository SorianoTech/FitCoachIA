"""Strict contract for the Trainer's output, mirroring ``interviewer_profile``.

The model returns exactly one JSON object per turn. Anything the schema does not
allow is rejected here rather than handed to the user, so a hallucinated plan
never reaches Telegram or the database.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MESOCYCLE_WEEKS = 4

# Estado de training_sessions: hay un plan vigente y el entrenador responde preguntas.
TRAINING_STATUS_ACTIVE = "active"


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
    weeks: list[TrainingWeek]
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


class TrainerTurn(PlanModel):
    """``plan`` delivers a new mesocycle; ``answer`` is a follow-up reply."""

    status: Literal["plan", "answer"]
    reply: str = Field(min_length=1)
    report: str | None = None
    plan: TrainingPlan | None = None

    @model_validator(mode="after")
    def validate_completion(self) -> "TrainerTurn":
        if self.status == "plan" and (self.report is None or self.plan is None):
            raise ValueError("A plan turn requires both report and plan")
        if self.status == "answer" and (self.report is not None or self.plan is not None):
            raise ValueError("An answer turn cannot include report or plan")
        return self
