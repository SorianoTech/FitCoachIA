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
    ) -> None: ...

    async def get_interview_status(self, chat_id: int) -> str | None: ...

    async def restart_interview(self, chat_id: int) -> None: ...

    async def complete_interview(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
        profile: InterviewerProfile,
        report: str,
    ) -> None: ...
