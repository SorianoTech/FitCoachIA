from datetime import datetime
from typing import Protocol

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerProfile


class ConversationRepository(Protocol):
    async def get_recent(self, chat_id: int, limit: int) -> list[ConversationMessage]: ...

    async def add_turn(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
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

    async def tokens_used_since(self, chat_id: int, since: datetime) -> int: ...
