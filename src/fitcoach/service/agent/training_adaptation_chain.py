import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Generic, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.exercise_catalogue import known_equipment
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.domain.trainer_plan import TrainerGenerationTrace, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    ReviewExtraction,
    SwapConstraints,
    SwapProposal,
    SwapRequest,
    prescribed_summary,
)
from fitcoach.infrastructure.config.settings import get_ia_settings
from fitcoach.infrastructure.observability.latency import timed
from fitcoach.infrastructure.prompts.prompt_loader import PromptLoader
from fitcoach.service.agent.llm_chain import AsyncChatModel, BaseLLMChain, strict_response_format
from fitcoach.service.agent.rag_context import build_rag_context
from fitcoach.service.agent.trainer_chain import _hash_text, build_trainer_model

ResultT = TypeVar("ResultT", bound=BaseModel)


@dataclass(frozen=True)
class AdaptationReply(Generic[ResultT]):
    result: ResultT
    token_usages: list[TokenUsage]
    trace: TrainerGenerationTrace | None = None


class TrainingAdaptationChain:
    def __init__(
        self,
        review_model: AsyncChatModel,
        swap_model: AsyncChatModel,
        model_name: str = "unknown",
        request_model: AsyncChatModel | None = None,
        extraction_model_name: str | None = None,
    ) -> None:
        self._review = BaseLLMChain(review_model, extraction_model_name or model_name)
        self._swap = BaseLLMChain(swap_model, model_name)
        self._request = BaseLLMChain(
            request_model or swap_model, extraction_model_name or model_name
        )
        self._loader = PromptLoader()
        self._model_name = model_name

    @timed("review_extraction", action="renewal")
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

    @timed("proposal", action="exercise_swap")
    async def propose_swap(
        self,
        profile: InterviewerProfile,
        request: SwapRequest,
        source: Exercise,
        candidates: Sequence[Exercise],
        plan: TrainingPlan | None = None,
        catalogue: Sequence[Exercise] = (),
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

        prompt = (
            self._loader.load_system_prompt("trainer", "swap_prompt.txt")
            + "\n"
            + build_rag_context(candidates)
        )
        result, usages = await self._swap._invoke_validated(
            [
                SystemMessage(content=prompt),
                HumanMessage(
                    content=json.dumps({
                        "profile": profile.model_dump(mode="json"),
                        "request": request.model_dump(mode="json"),
                        "source": asdict(source),
                        "affected_sessions": [
                            {
                                "week": week.week,
                                "intensity": week.intensity,
                                "session": day.model_dump(mode="json"),
                            }
                            for week in plan.weeks
                            if week.week >= request.from_week
                            for day in week.days
                            if any(
                                item.exercise_id == request.exercise_id for item in day.exercises
                            )
                        ]
                        if plan
                        else [],
                        "prescribed_weekly_sets_by_target": prescribed_summary(
                            plan, list(catalogue)
                        )
                        if plan
                        else {},
                        "session_exercise_metadata": [asdict(item) for item in catalogue],
                        "pending_prescriptions": [
                            {
                                "week": week.week,
                                "day": day.day,
                                "exercise": item.model_dump(mode="json"),
                            }
                            for week in plan.weeks
                            if week.week >= request.from_week
                            for day in week.days
                            for item in day.exercises
                            if item.exercise_id == request.exercise_id
                        ]
                        if plan
                        else [],
                    })
                ),
            ],
            SwapProposal,
            validate,
        )
        trace = TrainerGenerationTrace(
            model=self._model_name,
            skill_name="trainer-swap",
            prompt_hash=_hash_text(prompt),
            skill_hash=_hash_text(self._loader.load_system_prompt("trainer", "swap_prompt.txt")),
            retrieved_exercise_ids=tuple(sorted(allowed)),
        )
        return AdaptationReply(result, usages, trace)

    @timed("constraint_extraction", action="exercise_swap")
    async def extract_swap_constraints(
        self, profile: InterviewerProfile, request: SwapRequest
    ) -> AdaptationReply[SwapConstraints]:
        result, usages = await self._request._invoke_validated(
            [
                SystemMessage(
                    content=self._loader.load_system_prompt("trainer", "swap_request_prompt.txt")
                ),
                HumanMessage(
                    content=json.dumps({
                        "profile": profile.model_dump(mode="json"),
                        "request": request.model_dump(mode="json"),
                        "known_equipment": known_equipment(),
                    })
                ),
            ],
            SwapConstraints,
        )
        return AdaptationReply(result, usages)


@lru_cache
def get_training_adaptation_chain() -> TrainingAdaptationChain:
    settings = get_ia_settings()
    review = build_trainer_model(settings, "extraction").bind(
        response_format=strict_response_format(ReviewExtraction)
    )
    swap = build_trainer_model(settings).bind(response_format=strict_response_format(SwapProposal))
    request = build_trainer_model(settings, "extraction").bind(
        response_format=strict_response_format(SwapConstraints)
    )
    return TrainingAdaptationChain(
        review,
        swap,
        settings.trainer_generation_model or settings.model,
        request_model=request,
        extraction_model_name=settings.trainer_extraction_model or settings.model,
    )
