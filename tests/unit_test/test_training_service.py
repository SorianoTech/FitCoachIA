from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.constants import Constants
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.trainer_plan import PlannedExercise, TrainerTurn, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    Mesocycle,
    ReviewExtraction,
    SwapOption,
    SwapProposal,
    TrainingProfilePatch,
    TrainingWorkflow,
)
from fitcoach.repository.conversation_repository import ConversationRepository, StoredTrainingPlan
from fitcoach.repository.training_repository import TrainingRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.trainer_chain import TrainerChain, TrainerReply
from fitcoach.service.agent.training_adaptation_chain import (
    AdaptationReply,
    TrainingAdaptationChain,
)
from fitcoach.service.training_service import TrainingService
from tests.unit_test.conftest import build_plan_payload

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def collaborators(
    profile: InterviewerProfile,
) -> tuple[TrainingService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=TrainingRepository)
    repository.get_workflow.return_value = None
    repository.effective_profile.return_value = None
    repository.get_cycle.return_value = Mesocycle(
        id=1, started_at=NOW - timedelta(days=28), expected_end_at=NOW
    )
    flow = TrainingWorkflow(id=1, kind="renewal", base_plan_id=10, state="reviewing")
    repository.start.return_value = flow
    repository.claim_generation.return_value = flow
    repository.save.side_effect = lambda chat, current: current
    conversation = AsyncMock(spec=ConversationRepository)
    plan = TrainingPlan.model_validate(build_plan_payload())
    conversation.get_current_plan.return_value = StoredTrainingPlan(10, 1, plan, "base")
    conversation.get_interviewer_profile.return_value = profile
    conversation.tokens_used_since.return_value = 0
    trainer = AsyncMock(spec=TrainerChain)
    trainer.generate_next_plan.return_value = TrainerReply(
        TrainerTurn(status="plan", plan=plan, reply="draft", report="Adapted draft"), []
    )
    retriever = AsyncMock(spec=ExerciseRetriever)
    retriever.get_by_ids.return_value = [
        Exercise(
            101,
            "barbell bench press",
            target="pectorals",
            muscle_group="chest",
            equipment="barbell",
        )
    ]
    retriever.retrieve.return_value = retriever.get_by_ids.return_value
    adaptation = AsyncMock(spec=TrainingAdaptationChain)
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(), safety_hold=False, explanation="Sin cambios"
        ),
        [],
    )
    service = TrainingService(
        repository,
        conversation,
        trainer,
        retriever,
        adaptation,
        UsageLimits(1000, 800, timedelta(days=1)),
        clock=lambda: NOW,
    )
    return service, repository, conversation, trainer, adaptation


@pytest.mark.asyncio
async def test_renewal_requires_confirmed_closure(collaborators: tuple) -> None:
    service, repository, _, trainer, _ = collaborators
    result = await service.handle(7, "/train")
    assert result == [Constants.TRAINING_CLOSURE_QUESTION]
    trainer.generate_next_plan.assert_not_awaited()
    repository.get_workflow.return_value = repository.start.return_value
    result = await service.handle(7, "sí")
    repository.close_cycle.assert_awaited_once_with(7, NOW)
    assert result == [Constants.TRAINING_REVIEW_QUESTIONS["adherence"]]


@pytest.mark.asyncio
async def test_review_generates_draft_not_active_plan(collaborators: tuple) -> None:
    service, repository, _, trainer, _ = collaborators
    flow = repository.start.return_value
    flow.answers = {
        "closed": "confirmed",
        **dict.fromkeys(Constants.TRAINING_REVIEW_QUESTIONS, "sin cambios"),
    }
    repository.get_workflow.return_value = flow
    result = await service.handle(7, "generar")
    trainer.generate_next_plan.assert_awaited_once()
    context = trainer.generate_next_plan.await_args.args[0]
    assert context.previous_version == 1
    assert context.prescribed_summary["4"]["pectorals"] == 9
    assert any("confirmar 1" in item for item in result)
    repository.accept.assert_not_awaited()
    assert flow.state == "awaiting_confirmation"


@pytest.mark.asyncio
async def test_new_symptoms_stop_generation(collaborators: tuple) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    flow.answers = {
        "closed": "confirmed",
        **dict.fromkeys(Constants.TRAINING_REVIEW_QUESTIONS, "dolor"),
    }
    repository.get_workflow.return_value = flow
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(), safety_hold=True, explanation="Consultar"
        ),
        [],
    )
    assert Constants.TRAINING_SAFETY_MESSAGE in await service.handle(7, "generar")
    trainer.generate_next_plan.assert_not_awaited()
    assert await service.handle(7, "ahora genera") == [Constants.TRAINING_SAFETY_MESSAGE]


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["/train confirmar 1", "/train cancelar", "/train avisos off"])
async def test_controls_work_when_quota_is_exhausted(collaborators: tuple, control: str) -> None:
    service, _, conversation, trainer, _ = collaborators
    conversation.tokens_used_since.return_value = 2000
    responses = await service.handle(7, control)
    assert Constants.QUOTA_SOFT_MESSAGE not in responses
    trainer.generate_next_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_generation_checks_soft_quota(collaborators: tuple) -> None:
    service, repository, conversation, trainer, _ = collaborators
    flow = repository.start.return_value
    flow.answers = {
        "closed": "confirmed",
        **dict.fromkeys(Constants.TRAINING_REVIEW_QUESTIONS, "ok"),
    }
    repository.get_workflow.return_value = flow
    conversation.tokens_used_since.return_value = 900
    assert await service.handle(7, "generar") == [Constants.QUOTA_SOFT_MESSAGE]
    trainer.generate_next_plan.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "/train confirmar x",
        "/train inicio invalid",
        "/train posponer 2020-01-01",
        "/train avisos invalid",
    ],
)
async def test_invalid_controls_are_visible(collaborators: tuple, command: str) -> None:
    service, _, _, _, _ = collaborators
    assert await service.handle(7, command)


@pytest.mark.asyncio
async def test_swap_requires_selection_then_confirmation(collaborators: tuple) -> None:
    service, repository, conversation, _, adaptation = collaborators
    flow = TrainingWorkflow(id=3, base_plan_id=10, kind="exercise_swap", state="reviewing")
    repository.start.return_value = flow
    repository.claim_generation.return_value = flow
    source = Exercise(
        101, "barbell bench press", target="pectorals", muscle_group="chest", equipment="barbell"
    )
    candidate = Exercise(
        202, "other press", target="pectorals", muscle_group="chest", equipment="barbell"
    )
    service._retriever.get_by_ids.return_value = [source]
    service._retriever.retrieve_alternatives.return_value = [candidate]
    replacement = PlannedExercise(
        exercise_id=202, name="other press", sets=3, reps="8-10", rest_seconds=120, rpe=7.0
    )
    adaptation.propose_swap.return_value = AdaptationReply(
        SwapProposal(options=[SwapOption(exercise=replacement, rationale="Mismo target")]), []
    )
    result = await service.handle(7, "/train cambiar 101 2 preferencia")
    assert any("elegir 3" in item for item in result)
    repository.get_workflow.return_value = flow
    await service.handle(7, "/train elegir 3 1")
    original = conversation.get_current_plan.return_value.plan
    assert flow.draft.weeks[0] == original.weeks[0]
    assert flow.draft.weeks[1].days[0].exercises[0].exercise_id == 202
    repository.accept.assert_not_awaited()
    await service.handle(7, "/train confirmar 3")
    repository.accept.assert_awaited_once_with(7, 3, NOW)


@pytest.mark.asyncio
async def test_pain_is_not_treated_by_swap(collaborators: tuple) -> None:
    service, repository, _, _, adaptation = collaborators
    repository.start.return_value = TrainingWorkflow(
        id=3, base_plan_id=10, kind="exercise_swap", state="reviewing"
    )
    assert await service.handle(7, "/train cambiar 101 2 dolor") == [
        Constants.TRAINING_SAFETY_MESSAGE
    ]
    adaptation.propose_swap.assert_not_awaited()
