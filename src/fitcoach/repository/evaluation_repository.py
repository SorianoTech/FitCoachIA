from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class PollTarget:
    """Cycle and plan a due poll asks about."""

    mesocycle_id: int
    started_at: datetime | None
    thread_id: int | None
    plan_id: int
    goal: str | None


@dataclass(frozen=True)
class SentPoll:
    job_id: UUID
    chat_id: int
    target: PollTarget
    week_number: int
    poll_id: str
    message_id: int
    sent_at: datetime


class EvaluationRepository(Protocol):
    async def open_current_plan(self, mesocycle_id: int) -> PollTarget | None: ...
    async def previous_unanswered(self, chat_id: int) -> list[int]: ...
    async def save_sent(self, poll: SentPoll) -> None: ...
    async def record_answer(
        self, poll_id: str, user_id: int, score: int | None, now: datetime
    ) -> bool: ...
