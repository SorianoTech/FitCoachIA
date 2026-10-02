from dataclasses import dataclass
from datetime import datetime
from typing import Literal

MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    chat_id: int
    role: MessageRole
    content: str
    created_at: datetime
