import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Generic, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.training_lifecycle import ReviewExtraction, SwapProposal, SwapRequest
from fitcoach.infrastructure.config.settings import get_ia_settings
from fitcoach.infrastructure.prompts.prompt_loader import PromptLoader
from fitcoach.service.agent.llm_chain import AsyncChatModel, BaseLLMChain, strict_response_format
from fitcoach.service.agent.rag_context import build_rag_context
from fitcoach.service.agent.trainer_chain import build_trainer_model

ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True)
class AdaptationReply(Generic[ResultT]):
    result: ResultT
    token_usages: list[TokenUsage]


class TrainingAdaptationChain:
    def __init__(
        self, review_model: AsyncChatModel, swap_model: AsyncChatModel, model_name: str = "unknown"
    ) -> None:
        self._review = BaseLLMChain(review_model, model_name)
        self._swap = BaseLLMChain(swap_model, model_name)
        self._loader = PromptLoader()

    async def extract_review(
        self, profile: InterviewerProfile, answers: dict[str, str]
    ) -> AdaptationReply[ReviewExtraction]:
        result, usages = await self._review._invoke_validated(
            [
                SystemMessage(
                    content=self._loader.load_system_prompt("trainer", "review_prompt.txt")
                ),
                HumanMessage(
                    content=json.dumps({
                        "profile": profile.model_dump(mode="json"),
                        "answers": answers,
                    })
                ),
            ],
            ReviewExtraction,
        )
        return AdaptationReply(result, usages)

    async def propose_swap(
        self,
        profile: InterviewerProfile,
        request: SwapRequest,
        source: Exercise,
        candidates: Sequence[Exercise],
    ) -> AdaptationReply[SwapProposal]:
        allowed = {item.id: item for item in candidates}

        def validate(raw: str) -> SwapProposal:
            proposal = SwapProposal.model_validate_json(raw)
            ids = [option.exercise.exercise_id for option in proposal.options]
            invalid = len(ids) != len(set(ids)) or any(
                item.exercise.exercise_id not in allowed
                or item.exercise.name != allowed[item.exercise.exercise_id].name
                for item in proposal.options
            )
            if invalid:
                raise ValidationError.from_exception_data(
                    SwapProposal.__name__,
                    [
                        InitErrorDetails(
                            type=PydanticCustomError(
                                "invalid_candidates", "Use distinct canonical catalogue exercises"
                            ),
                            loc=("options",),
                            input=raw,
                        )
                    ],
                )
            return proposal

        result, usages = await self._swap._invoke_validated(
            [
                SystemMessage(
                    content=self._loader.load_system_prompt("trainer", "swap_prompt.txt")
                    + "\n"
                    + build_rag_context(candidates)
                ),
                HumanMessage(
                    content=json.dumps({
                        "profile": profile.model_dump(mode="json"),
                        "request": request.model_dump(mode="json"),
                        "source": {"id": source.id, "name": source.name, "target": source.target},
                    })
                ),
            ],
            SwapProposal,
            validate,
        )
        return AdaptationReply(result, usages)


@lru_cache
def get_training_adaptation_chain() -> TrainingAdaptationChain:
    settings = get_ia_settings()
    review = build_trainer_model(settings).bind(
        response_format=strict_response_format(ReviewExtraction)
    )
    swap = build_trainer_model(settings).bind(response_format=strict_response_format(SwapProposal))
    return TrainingAdaptationChain(review, swap, settings.model)
