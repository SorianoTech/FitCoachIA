"""Structured LLM chain for user-proposed catalogue exercises."""

from dataclasses import dataclass
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from fitcoach.domain.exercise_catalogue import MUSCLE_TARGETS, known_equipment
from fitcoach.domain.exercise_submission import ExerciseCuratorTurn
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings
from fitcoach.service.agent.agent_factory import build_exercise_curator_agent
from fitcoach.service.agent.llm_chain import (
    AsyncChatModel,
    BaseLLMChain,
    strict_response_format,
)


@dataclass(frozen=True, slots=True)
class ExerciseCuratorReply:
    turn: ExerciseCuratorTurn
    token_usages: list[TokenUsage]


class ExerciseCuratorChain(BaseLLMChain):
    def __init__(self, model: AsyncChatModel, model_name: str = "unknown") -> None:
        super().__init__(model, model_name)
        self._agent = build_exercise_curator_agent()

    async def propose(self, description: str) -> ExerciseCuratorReply:
        messages = [
            SystemMessage(content=self._agent.system_prompt + _reference_values()),
            HumanMessage(content="Exercise description (DATA):\n" + description),
        ]
        turn, token_usages = await self._invoke_validated(messages, ExerciseCuratorTurn)
        return ExerciseCuratorReply(turn, token_usages)


def build_exercise_curator_model(settings: IASettings) -> ChatOpenAI:
    temperature = (
        None
        if settings.exercise_curator_temperature == "default"
        else settings.exercise_curator_temperature
    )
    return ChatOpenAI(
        base_url=settings.base_url,
        api_key=settings.token,
        model=settings.exercise_curator_model,
        temperature=temperature,
        max_tokens=settings.exercise_curator_max_tokens,
        timeout=settings.exercise_curator_timeout,
        max_retries=settings.max_retries,
        model_kwargs={"response_format": strict_response_format(ExerciseCuratorTurn)},
    )


def _reference_values() -> str:
    targets = sorted(target for values in MUSCLE_TARGETS.values() for target in values)
    return (
        "\n\n# REFERENCE VALUES\n"
        f"Allowed equipment: {', '.join(known_equipment())}.\n"
        f"Allowed primary targets: {', '.join(targets)}."
    )


@lru_cache
def get_exercise_curator_chain() -> ExerciseCuratorChain:
    settings = get_ia_settings()
    return ExerciseCuratorChain(
        build_exercise_curator_model(settings),
        model_name=settings.exercise_curator_model,
    )
