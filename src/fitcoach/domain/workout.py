"""Real workout measurements; prescription positions are zero-based and immutable."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from fitcoach.domain.trainer_plan import PlanModel, TrainingDay, TrainingPlan
from fitcoach.domain.training_lifecycle import Mesocycle

MAX_EXERCISES = 100
MAX_HISTORY = 100
WorkoutStatus = Literal["in_progress", "completed"]


class WorkoutNotFoundError(Exception):
    pass


class WorkoutConflictError(Exception):
    pass


class WorkoutValidationError(Exception):
    pass


class WorkoutSet(PlanModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    number: int = Field(ge=1, le=10)
    reps: int | None = Field(default=None, ge=1, le=10000)
    duration_seconds: int | None = Field(default=None, ge=1, le=86400)
    weight_kg: float | None = Field(default=None, ge=0, le=2000)
    rpe: float | None = Field(default=None, ge=1, le=10)
    completed: bool

    @model_validator(mode="after")
    def validate_measurement(self) -> "WorkoutSet":
        if self.reps is not None and self.duration_seconds is not None:
            raise ValueError("Record reps or duration, not both")
        if self.completed and self.reps is None and self.duration_seconds is None:
            raise ValueError("Completed sets require reps or duration")
        return self


class WorkoutExercise(PlanModel):
    position: int = Field(ge=0, lt=MAX_EXERCISES)
    skipped: bool
    sets: list[WorkoutSet] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_skipped(self) -> "WorkoutExercise":
        if len({item.number for item in self.sets}) != len(self.sets):
            raise ValueError("Set numbers must be unique")
        if self.skipped and any(
            item.completed
            or item.reps is not None
            or item.duration_seconds is not None
            or item.weight_kg is not None
            or item.rpe is not None
            for item in self.sets
        ):
            raise ValueError("Skipped exercises cannot contain performed measurements")
        return self


class StartWorkout(PlanModel):
    request_id: UUID = Field(strict=False)
    plan_id: int = Field(ge=1)
    week: int = Field(ge=1, le=4)
    day: int = Field(ge=1, le=7)


class UpdateWorkout(PlanModel):
    revision: int = Field(ge=0)
    status: WorkoutStatus
    exercises: list[WorkoutExercise] = Field(min_length=1, max_length=MAX_EXERCISES)

    def validate_prescription(self, prescription: TrainingDay) -> None:
        positions = [item.position for item in self.exercises]
        if sorted(positions) != list(range(len(prescription.exercises))):
            raise WorkoutValidationError("Exactly one entry per prescribed exercise is required")
        performed = False
        for item in self.exercises:
            planned = prescription.exercises[item.position]
            if sorted(entry.number for entry in item.sets) != list(range(1, planned.sets + 1)):
                raise WorkoutValidationError("All prescribed set numbers are required")
            performed |= any(entry.completed for entry in item.sets)
            if (
                self.status == "completed"
                and not item.skipped
                and not all(entry.completed for entry in item.sets)
            ):
                raise WorkoutValidationError("Complete every prescribed set or skip the exercise")
        if self.status == "completed" and not performed:
            raise WorkoutValidationError("Completion requires at least one performed set")


class WorkoutSession(PlanModel):
    id: int
    plan_id: int
    mesocycle_id: int | None
    week: int
    day: int
    revision: int
    status: WorkoutStatus
    started_at: datetime
    completed_at: datetime | None
    prescription: TrainingDay
    exercises: list[WorkoutExercise]


class WorkoutBootstrap(PlanModel):
    plan_id: int
    version: int
    plan: TrainingPlan
    cycle: Mesocycle | None
    current_week: int | None
    calendar_status: str


class ExerciseHistory(PlanModel):
    date: str
    session_id: int
    total_reps: int | None
    total_duration_seconds: int | None = None
    total_sets: int
    max_weight_kg: float | None
    average_rpe: float | None


class ExerciseProgress(PlanModel):
    exercise_id: int
    name: str
    history: list[ExerciseHistory]


class WorkoutProgress(PlanModel):
    completed_sessions: int
    exercises: list[ExerciseProgress]
    history_limit: int = MAX_HISTORY
    history_truncated: bool = False
