from dataclasses import dataclass
from typing import Protocol

from fitcoach.domain.agents import AgentType
from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.trainer_plan import TrainingPlan


@dataclass(frozen=True, slots=True)
class StoredTrainingPlan:
    """A persisted plan plus the version it was stored as."""

    id: int
    version: int
    plan: TrainingPlan
    report: str


class ConversationRepository(Protocol):
    async def get_recent(
        self,
        chat_id: int,
        limit: int,
        agent: str = AgentType.INTERVIEWER.value,
    ) -> list[ConversationMessage]: ...

    async def add_turn(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        agent: str = AgentType.INTERVIEWER.value,
    ) -> int: ...

    async def get_interview_status(self, chat_id: int) -> str | None: ...

    async def restart_interview(self, chat_id: int) -> None: ...

    async def complete_interview(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        profile: InterviewerProfile,
        report: str,
    ) -> int: ...

    async def get_interviewer_profile(self, chat_id: int) -> InterviewerProfile | None: ...

    async def get_training_status(self, chat_id: int) -> str | None: ...

    async def get_current_plan(self, chat_id: int) -> StoredTrainingPlan | None: ...

    async def save_training_plan(
        self,
        chat_id: int,
        plan: TrainingPlan,
        report: str,
        user_content: str,
        assistant_content: str,
    ) -> int: ...

    async def record_token_usage(
        self,
        chat_id: int,
        agent: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str,
        conversation_message_id: int | None,
    ) -> None: ...
