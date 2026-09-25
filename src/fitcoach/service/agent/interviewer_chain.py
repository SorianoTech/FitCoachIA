import logging
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from fitcoach.domain.conversation import ConversationMessage
from fitcoach.domain.interviewer_profile import InterviewerTurn
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_interviewer_agent
from fitcoach.service.agent.llm_chain import (
    AsyncChatModel,
    BaseLLMChain,
    InvalidModelOutputError,
)

logger = logging.getLogger(__name__)

# Kept as an alias: the interviewer's "invalid result" is the shared
# invalid-output error, and existing call sites import it under this name.
InterviewerResultError = InvalidModelOutputError


@dataclass(frozen=True, slots=True)
class InterviewerReply:
    """``respond()``'s result: the validated turn plus one ``TokenUsage`` per LLM call.

    ``token_usages`` has two entries when the JSON-repair retry fires (the
    original malformed call still consumed tokens and must not be discarded),
    and is empty when the model/test double reports no usage metadata.
    """

    turn: InterviewerTurn
    token_usages: list[TokenUsage]


class InterviewerChain(BaseLLMChain):
    def __init__(
        self,
        model: AsyncChatModel,
        model_name: str = "unknown",
        skill_name: str = "interviewer",
    ) -> None:
        super().__init__(model, model_name)
        self._agent = build_interviewer_agent(skill_name=skill_name)

    async def respond(
        self, user_message: str, history: Sequence[ConversationMessage]
    ) -> InterviewerReply:
        messages = [
            SystemMessage(content=self._agent.insert_context()),
            *self._to_langchain_messages(history),
            HumanMessage(content=user_message),
        ]
        turn, token_usages = await self._invoke_validated(messages, InterviewerTurn)
        return InterviewerReply(turn=turn, token_usages=token_usages)


def _build_model(settings: IASettings) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        api_key=settings.token,
        model=settings.model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens or None,
        timeout=settings.timeout_seconds or None,
        model_kwargs={"response_format": {"type": "json_object"}},
    )


@lru_cache
def get_interviewer_chain() -> InterviewerChain:
    settings = get_ia_settings()
    return InterviewerChain(
        _build_model(settings), model_name=settings.model, skill_name=settings.skill
    )
