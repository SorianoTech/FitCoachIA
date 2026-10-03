"""Confirmed training lifecycle, independent of Telegram and persistence."""

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import (
    Commitment,
    Goal,
    Injury,
    InterviewerProfile,
    Sleep,
    Training,
)
from fitcoach.domain.trainer_plan import (
    MESOCYCLE_WEEKS,
    RPE_CAPS,
    PlanModel,
    PlannedExercise,
    TrainingPlan,
)

WorkflowState = Literal[
    "reviewing", "generating", "awaiting_confirmation", "accepted", "cancelled", "stale"
]
ChangeKind = Literal["initial", "renewal", "exercise_swap"]


class TrainingProfilePatch(PlanModel):
    goal: Goal | None = None
    commitment: Commitment | None = None
    training: Training | None = None
    sleep: Sleep | None = None
    injuries: list[Injury] | None = None

    def apply(self, profile: InterviewerProfile) -> InterviewerProfile:
        data = profile.model_dump(mode="json")
        data.update(self.model_dump(mode="json", exclude_none=True))
        return InterviewerProfile.model_validate_json(json.dumps(data))


class ReviewSummary(PlanModel):
    adherence: str = Field(min_length=1)
    results: str = Field(min_length=1)
    recovery: str = Field(min_length=1)
    discomfort: str = Field(min_length=1)
    preferences: str = Field(min_length=1)
    changes: str = Field(min_length=1)


class TrainingReview(ReviewSummary):
    user_feedback: str = ""
    profile_patch: TrainingProfilePatch = Field(default_factory=TrainingProfilePatch)
    safety_hold: bool = False


class ReviewExtraction(PlanModel):
    profile_patch: TrainingProfilePatch
    safety_hold: bool
    explanation: str = Field(min_length=1)
    summary: ReviewSummary | None = Field(default_factory=lambda: None)
    clarification: str | None = Field(default_factory=lambda: None, min_length=1)


class Mesocycle(PlanModel):
    id: int
    started_at: datetime | None
    expected_end_at: datetime | None
    completed_at: datetime | None = None
    reminders_enabled: bool = True

    def due(self, now: datetime) -> bool:
        return self.expected_end_at is not None and now >= self.expected_end_at


class ExerciseSlot(PlanModel):
    week: int = Field(ge=1, le=MESOCYCLE_WEEKS)
    day: int = Field(ge=1, le=7)
    index: int = Field(ge=0)


class SwapRequest(PlanModel):
    exercise_id: int = Field(ge=1)
    from_week: int = Field(ge=1, le=MESOCYCLE_WEEKS)
    reason: str = Field(min_length=1)


class SwapOption(PlanModel):
    exercise: PlannedExercise
    rationale: str = Field(min_length=1)


class SwapProposal(PlanModel):
    options: list[SwapOption] = Field(max_length=3)
    safety_hold: bool = Field(default_factory=lambda: False)

    @model_validator(mode="after")
    def validate_safety(self) -> "SwapProposal":
        if self.safety_hold == bool(self.options):
            raise ValueError("Safe proposals need options; safety holds prohibit them")
        return self


class TrainingWorkflow(PlanModel):
    id: int
    kind: Literal["renewal", "exercise_swap"]
    base_plan_id: int
    state: WorkflowState
    revision: int = 0
    answers: dict[str, str] = Field(default_factory=dict)
    review: TrainingReview | None = None
    effective_profile: InterviewerProfile | None = None
    swap: SwapRequest | None = None
    options: list[SwapOption] = Field(default_factory=list)
    draft: TrainingPlan | None = None
    base_draft: TrainingPlan | None = None
    base_report: str | None = None
    report: str | None = None
    lease_until: datetime | None = None
    generation_key: str | None = None
    prompt_trace: dict[str, str | list[int]] | None = None
    generation_traces: list[dict[str, str | list[int]]] = Field(default_factory=list)


class TrainingAdaptationContext(PlanModel):
    profile: InterviewerProfile
    previous_plan: TrainingPlan
    previous_version: int
    review: TrainingReview
    prescribed_summary: dict[str, dict[str, int]]

    @model_validator(mode="after")
    def no_unsafe_generation(self) -> "TrainingAdaptationContext":
        if self.review.safety_hold:
            raise ValueError("New concerning symptoms require professional review, not generation")
        return self


def expected_end(start: datetime) -> datetime:
    if start.tzinfo is None:
        raise ValueError("Mesocycle dates must be timezone-aware")
    return start + timedelta(weeks=MESOCYCLE_WEEKS)


def prescribed_summary(plan: TrainingPlan, catalogue: list[Exercise]) -> dict[str, dict[str, int]]:
    by_id = {exercise.id: exercise for exercise in catalogue}
    result: dict[str, dict[str, int]] = {}
    for week in plan.weeks:
        targets: dict[str, int] = {}
        for day in week.days:
            for item in day.exercises:
                metadata = by_id.get(item.exercise_id)
                target = metadata.target if metadata and metadata.target else "unknown"
                targets[target] = targets.get(target, 0) + item.sets
        result[str(week.week)] = targets
    return result


def apply_swap(
    plan: TrainingPlan, request: SwapRequest, replacement: PlannedExercise
) -> TrainingPlan:
    data = plan.model_dump(mode="json")
    updated = plan.model_copy(deep=True)
    reference = next(
        (
            item
            for week in plan.weeks
            if week.week >= request.from_week
            for day in week.days
            for item in day.exercises
            if item.exercise_id == request.exercise_id
        ),
        None,
    )
    if reference is None:
        raise ValueError("No pending occurrences match the exercise")
    changed = False
    for week in updated.weeks:
        if week.week < request.from_week:
            continue
        for day in week.days:
            for index, exercise in enumerate(day.exercises):
                if exercise.exercise_id == request.exercise_id:
                    item = replacement.model_copy(deep=True)
                    item.sets = max(
                        1, min(10, round(replacement.sets * exercise.sets / reference.sets))
                    )
                    values = [value for value in (item.rpe, exercise.rpe) if value is not None]
                    cap = RPE_CAPS.get(week.week)
                    if values and cap is not None:
                        values.append(cap)
                    item.rpe = min(values) if values else None
                    day.exercises[index] = item
                    changed = True
            ids = [exercise.exercise_id for exercise in day.exercises]
            if len(ids) != len(set(ids)):
                raise ValueError("The replacement would repeat an exercise within a day")
    if not changed:
        raise ValueError("No pending occurrences match the exercise")
    data.update(updated.model_dump(mode="json"))
    return TrainingPlan.model_validate(data)


def utc_now() -> datetime:
    return datetime.now(UTC)
