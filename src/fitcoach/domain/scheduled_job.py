"""Generic scheduled job: types, lifecycle and the outcome a handler reports."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class JobType(StrEnum):
    TRAINING_REMINDER = "training_reminder"
    EVALUATION_POLL = "evaluation_poll"


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def evaluation_poll_key(mesocycle_id: int, week: int) -> str:
    return f"{JobType.EVALUATION_POLL}:{mesocycle_id}:{week}"


def training_reminder_key(mesocycle_id: int, occasion: int) -> str:
    return f"{JobType.TRAINING_REMINDER}:{mesocycle_id}:{occasion}"


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    job_type: JobType
    chat_id: int
    payload: dict[str, object]
    attempts: int
    execution_date: datetime


@dataclass(frozen=True)
class JobOutcome:
    """Final state of a run; ``retry_at`` is set only when the job goes back to pending."""

    state: JobState
    retry_at: datetime | None = field(default=None)

    @classmethod
    def done(cls) -> "JobOutcome":
        return cls(JobState.DONE)

    @classmethod
    def failed(cls) -> "JobOutcome":
        return cls(JobState.FAILED)

    @classmethod
    def cancelled(cls) -> "JobOutcome":
        return cls(JobState.CANCELLED)

    @classmethod
    def retry(cls, retry_at: datetime) -> "JobOutcome":
        return cls(JobState.PENDING, retry_at)
