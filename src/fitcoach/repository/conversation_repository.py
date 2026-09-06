from typing import Protocol

from fitcoach.domain.conversation import ConversationMessage, MessageRole


class ConversationRepository(Protocol):
    async def get_recent(self, chat_id: int, limit: int) -> list[ConversationMessage]: ...

    async def add(self, chat_id: int, role: MessageRole, content: str) -> None: ...
