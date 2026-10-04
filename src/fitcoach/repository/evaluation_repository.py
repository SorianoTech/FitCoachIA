from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


class EvaluationConflictError(RuntimeError):
    """The poll is no longer locked by the worker that claimed it."""


@dataclass(frozen=True)
class EvaluationDelivery:
    id: int
    chat_id: int
    thread_id: int | None
    week_number: int
    goal: str | None
    attempts: int
    # Last sent poll of the cycle still unanswered: the worker closes it.
    previous_message_id: int | None


class EvaluationRepository(Protocol):
    async def claim(
        self, now: datetime, sending_timeout: timedelta
    ) -> EvaluationDelivery | None: ...
    async def mark_sent(
        self, delivery: EvaluationDelivery, poll_id: str, message_id: int, now: datetime
    ) -> None: ...
    async def finish(
        self, delivery: EvaluationDelivery, retry_at: datetime | None = None, failed: bool = False
    ) -> None: ...
    async def record_answer(
        self, poll_id: str, user_id: int, score: int | None, now: datetime
    ) -> bool: ...
