import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_interviewer_agent

logger = logging.getLogger(__name__)


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage: ...


class InterviewerChain:
    def __init__(self, model: AsyncChatModel) -> None:
        self._model = model
        self._agent = build_interviewer_agent()

    async def respond(self, user_message: str, history: Sequence[ConversationMessage]) -> str:
        response = await self._model.ainvoke([
            SystemMessage(content=self._agent.insert_context()),
            *self._to_langchain_messages(history),
            HumanMessage(content=user_message),
        ])
        if not isinstance(response.content, str):
            logger.error(
                "Interviewer model returned non-text content: %s", type(response.content).__name__
            )
            return ""
        return response.content.strip()

    @staticmethod
    def _to_langchain_messages(history: Sequence[ConversationMessage]) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for message in history:
            if message.role == "user":
                messages.append(HumanMessage(content=message.content))
            else:
                messages.append(AIMessage(content=message.content))
        return messages


def _build_model(settings: IASettings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        api_key=settings.token,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens or None,
        timeout=settings.timeout_seconds or None,
    )


@lru_cache
def get_interviewer_chain() -> InterviewerChain:
    return InterviewerChain(_build_model(get_ia_settings()))
