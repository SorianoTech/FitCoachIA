import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerTurn
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_interviewer_agent

logger = logging.getLogger(__name__)


class AsyncChatModel(Protocol):
    async def ainvoke(self, input: list[BaseMessage]) -> BaseMessage: ...


class InterviewerResultError(ValueError):
    pass


class InterviewerChain:
    def __init__(self, model: AsyncChatModel) -> None:
        self._model = model
        self._agent = build_interviewer_agent()

    async def respond(
        self, user_message: str, history: Sequence[ConversationMessage]
    ) -> InterviewerTurn:
        messages = [
            SystemMessage(content=self._agent.insert_context()),
            *self._to_langchain_messages(history),
            HumanMessage(content=user_message),
        ]
        raw_result = await self._invoke(messages)
        try:
            return InterviewerTurn.model_validate_json(raw_result)
        except ValidationError as exc:
            logger.warning("Interviewer result was invalid; requesting a repair: %s", exc)
            repaired_result = await self._invoke([
                SystemMessage(
                    content=(
                        "Return only a valid JSON object matching the required interviewer result "
                        f"schema. Fix these validation errors: {exc}"
                    )
                ),
                HumanMessage(content=raw_result),
            ])
            try:
                return InterviewerTurn.model_validate_json(repaired_result)
            except ValidationError as repair_error:
                raise InterviewerResultError(
                    "Interviewer result could not be repaired"
                ) from repair_error

    async def _invoke(self, messages: list[BaseMessage]) -> str:
        response = await self._model.ainvoke(messages)
        if not isinstance(response.content, str):
            raise InterviewerResultError("Interviewer model returned non-text content")
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
