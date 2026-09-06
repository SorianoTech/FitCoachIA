from typing import Protocol

from fitcoach.domain.conversation import ConversationMessage


class ConversationRepository(Protocol):
    async def get_recent(self, chat_id: int, limit: int) -> list[ConversationMessage]: ...

    async def add_turn(
        self,
        chat_id: int,
        user_content: str,
        assistant_content: str,
    ) -> None: ...
