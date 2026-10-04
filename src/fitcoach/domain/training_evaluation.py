"""Weekly satisfaction poll of a mesocycle: schedule, answer scale and delivery states."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from fitcoach.domain.trainer_plan import MESOCYCLE_WEEKS

EVALUATION_PERIOD: Final = timedelta(weeks=1)
MIN_SCORE: Final = 0
MAX_SCORE: Final = 5


class EvaluationState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


def due_at(started_at: datetime, week: int) -> datetime:
    return started_at + week * EVALUATION_PERIOD


def score_from_option(option_ids: Sequence[int]) -> int | None:
    """The chosen option index is the score; an empty list means the vote was retracted."""
    if not option_ids:
        return None
    score = option_ids[0]
    if not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"Option {score} is outside the {MIN_SCORE}-{MAX_SCORE} scale")
    return score


def _require_aware(*dates: datetime) -> None:
    if any(date.tzinfo is None for date in dates):
        raise ValueError("Evaluation dates must be timezone-aware")


def due_week(started_at: datetime, now: datetime) -> int | None:
    """Most recent week whose poll is due, capped at the last week of the mesocycle."""
    _require_aware(started_at, now)
    elapsed = (now - started_at) // EVALUATION_PERIOD
    if elapsed < 1:
        return None
    return min(elapsed, MESOCYCLE_WEEKS)


def upcoming_polls(started_at: datetime, now: datetime) -> list[tuple[int, datetime]]:
    """Weekly polls still ahead of ``now``; past weeks are never asked late."""
    _require_aware(started_at, now)
    return [
        (week, due)
        for week in range(1, MESOCYCLE_WEEKS + 1)
        if (due := due_at(started_at, week)) > now
    ]
