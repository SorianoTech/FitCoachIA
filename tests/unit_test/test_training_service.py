from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from telegram.error import RetryAfter

from fitcoach.domain.constants import Constants
from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.trainer_plan import PlannedExercise, TrainerTurn, TrainingPlan
from fitcoach.domain.training_lifecycle import (
    Mesocycle,
    ReviewExtraction,
    ReviewSummary,
    SwapConstraints,
    SwapOption,
    SwapProposal,
    TrainingProfilePatch,
    TrainingWorkflow,
)
from fitcoach.repository.conversation_repository import ConversationRepository, StoredTrainingPlan
from fitcoach.repository.training_repository import ReminderDelivery, TrainingRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever
from fitcoach.service.agent.trainer_chain import TrainerChain, TrainerReply
from fitcoach.service.agent.training_adaptation_chain import (
    AdaptationReply,
    TrainingAdaptationChain,
)
from fitcoach.service.training_service import TrainingService
from tests.unit_test.conftest import build_plan_payload

NOW = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.asyncio
@pytest.mark.parametrize("button", [True, False])
async def test_quick_review_generates_in_one_interaction_without_extraction(
    collaborators: tuple, button: bool
) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    repository.get_workflow.return_value = flow
    result = (
        await service.callback(7, "tr:good:1:0")
        if button
        else await service.handle(7, "terminé y todo bien")
    )
    repository.close_cycle.assert_awaited_once_with(7, NOW, expected_plan_id=10)
    adaptation.extract_review.assert_not_awaited()
    trainer.generate_next_plan.assert_awaited_once()
    context = trainer.generate_next_plan.await_args.args[0]
    assert "no informado" in context.review.adherence
    assert "no aporta mejoras" in context.review.results
    assert context.profile.injuries == (await service.profile(7)).injuries
    assert len(result) == 1
    assert "TU SIGUIENTE MESOCICLO" in result[0]
    repository.accept.assert_not_awaited()


@pytest.mark.asyncio
async def test_renewal_includes_real_performance_from_same_cycle(collaborators: tuple) -> None:
    service, repository, _, trainer, _ = collaborators
    recorded = {"completed_sessions": 2, "source": "self_recorded"}
    summary = AsyncMock(return_value=recorded)
    service._performance_summary = summary
    repository.get_workflow.return_value = repository.start.return_value
    await service.callback(7, "tr:good:1:0")
    summary.assert_awaited_once_with(7, 1)
    context = trainer.generate_next_plan.await_args.args[0]
    assert context.recorded_performance == recorded
    assert "no informado" in context.review.adherence
    repository.accept.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_cycle_does_not_invent_recorded_performance(collaborators: tuple) -> None:
    service, repository, _, trainer, _ = collaborators
    summary = AsyncMock()
    service._performance_summary = summary
    repository.get_cycle.return_value = None
    flow = repository.start.return_value
    flow.answers = {
        "closed": "confirmed",
        **dict.fromkeys(Constants.TRAINING_REVIEW_QUESTIONS, "sin cambios"),
    }
    repository.get_workflow.return_value = flow
    await service.handle(7, "generar")
    summary.assert_not_awaited()
    assert trainer.generate_next_plan.await_args.args[0].recorded_performance == {}


@pytest.mark.asyncio
async def test_trainer_reloads_database_limits_for_expensive_actions(collaborators: tuple) -> None:
    service, _, conversation, _, _ = collaborators
    conversation.tokens_used_since.return_value = 50
    resolver = AsyncMock(return_value=UsageLimits(100, 40, timedelta(minutes=5)))
    service._quota_resolver = resolver
    assert await service._quota(7)
    resolver.return_value = UsageLimits(100, 60, timedelta(minutes=10))
    assert not await service._quota(7)
    assert resolver.await_count == 2
    assert conversation.tokens_used_since.await_args.args == (7, NOW - timedelta(minutes=10))


@pytest.mark.asyncio
async def test_open_review_needs_only_one_answer_and_retains_raw_feedback(
    collaborators: tuple,
) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    repository.get_workflow.return_value = flow
    assert await service.callback(7, "tr:changes:1:0") == [Constants.TRAINING_OPEN_REVIEW]
    feedback = "Sin molestias nuevas, prefiero mancuernas y solo tengo 3 días."
    summary = ReviewSummary(**dict.fromkeys(Constants.TRAINING_REVIEW_QUESTIONS, "No informado"))
    summary.preferences = "Prefiere mancuernas."
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(),
            safety_hold=False,
            explanation="Cambios recogidos",
            summary=summary,
        ),
        [],
    )
    result = await service.handle(7, feedback)
    assert adaptation.extract_review.await_args.args[1]["open_review"] == feedback
    context = trainer.generate_next_plan.await_args.args[0]
    assert context.review.user_feedback == feedback
    assert context.review.preferences == "Prefiere mancuernas."
    assert "TU SIGUIENTE MESOCICLO" in result[0]


@pytest.mark.asyncio
async def test_essential_clarification_resumes_without_repeating_review(
    collaborators: tuple,
) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    flow.answers = {"closed": "confirmed", "review_mode": "open"}
    repository.get_workflow.return_value = flow
    question = "¿Qué material tienes disponible?"
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(),
            safety_hold=False,
            explanation="Material ambiguo",
            clarification=question,
        ),
        [],
    )
    assert await service.handle(7, "Entrenaré en casa, sin molestias nuevas.") == [question]
    trainer.generate_next_plan.assert_not_awaited()
    assert await service.handle(7, "/train revisar") == [question]
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(),
            safety_hold=False,
            explanation="Aclarado",
        ),
        [],
    )
    await service.handle(7, "Tengo mancuernas.")
    answers = adaptation.extract_review.await_args.args[1]
    assert "Entrenaré en casa" in answers["open_review"]
    assert question in answers["open_review"]
    assert "Tengo mancuernas" in answers["open_review"]
    trainer.generate_next_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_review_symptoms_override_clarification_and_block_quick_path(
    collaborators: tuple,
) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    flow.answers = {"closed": "confirmed", "review_mode": "open"}
    repository.get_workflow.return_value = flow
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(),
            safety_hold=True,
            explanation="Consultar profesional",
            clarification="¿Qué material tienes?",
        ),
        [],
    )
    assert Constants.TRAINING_SAFETY_MESSAGE in await service.handle(7, "Dolor nuevo")
    assert await service.callback(7, "tr:good:1:0") == [Constants.TRAINING_CALLBACK_INVALID]
    trainer.generate_next_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_quick_review_survives_quota_limit_and_stale_button(collaborators: tuple) -> None:
    service, repository, conversation, trainer, _ = collaborators
    flow = repository.start.return_value
    flow.revision = 2
    repository.get_workflow.return_value = flow
    assert await service.callback(7, "tr:good:1:1") == [Constants.TRAINING_CALLBACK_INVALID]
    repository.close_cycle.assert_not_awaited()
    conversation.tokens_used_since.return_value = 900
    assert await service.callback(7, "tr:good:1:2") == [Constants.QUOTA_SOFT_MESSAGE]
    assert flow.answers["quick_review"] == "true"
    trainer.generate_next_plan.assert_not_awaited()
    conversation.tokens_used_since.return_value = 0
    await service.handle(7, "generar")
    trainer.generate_next_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_partial_review_is_preserved_and_checked_for_safety(
    collaborators: tuple,
) -> None:
    service, repository, _, trainer, adaptation = collaborators
    flow = repository.start.return_value
    flow.answers = {"closed": "confirmed", "discomfort": "Dolor nuevo de rodilla"}
    repository.get_workflow.return_value = flow
    adaptation.extract_review.return_value = AdaptationReply(
        ReviewExtraction(
            profile_patch=TrainingProfilePatch(), safety_hold=True, explanation="Consultar"
        ),
        [],
    )
    assert Constants.TRAINING_SAFETY_MESSAGE in await service.callback(7, "tr:good:1:0")
    assert flow.answers["discomfort"] == "Dolor nuevo de rodilla"
    adaptation.extract_review.assert_awaited_once()
    trainer.generate_next_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_equipment_gets_natural_clarification(collaborators: tuple) -> None:
    service, repository, conversation, trainer, adaptation = collaborators
    flow = repository.start.return_value
    repository.get_workflow.return_value = flow
    profile = conversation.get_interviewer_profile.return_value
    profile.training.equipment = ["unknown gadget"]
    assert await service.callback(7, "tr:good:1:0") == [Constants.TRAINING_EQUIPMENT_QUESTION]
    assert flow.state == "reviewing"
    assert flow.review is None
    assert "quick_review" not in flow.answers
    trainer.generate_next_plan.assert_not_awaited()
    profile.training.equipment = ["barbell"]
    await service.handle(7, "Tengo barra")
    adaptation.extract_review.assert_awaited_once()
    trainer.generate_next_plan.assert_awaited_once()


@pytest.fixture
def collaborators(
    profile: InterviewerProfile,
) -> tuple[TrainingService, AsyncMock, AsyncMock, AsyncMock, AsyncMock]:
    repository = AsyncMock(spec=TrainingRepository)
    repository.get_workflow.return_value = None
    repository.reserve_interaction_reminder.return_value = None
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
    adaptation.extract_swap_constraints.return_value = AdaptationReply(
        SwapConstraints(excluded_equipment=[], safety_hold=False, clarification=None), []
    )
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
    result = await service.handle(7, "/train revisar")
    assert result == [Constants.TRAINING_CLOSURE_QUESTION]
    trainer.generate_next_plan.assert_not_awaited()
    repository.get_workflow.return_value = repository.start.return_value
    result = await service.handle(7, "sí")
    repository.close_cycle.assert_awaited_once_with(7, NOW, expected_plan_id=10)
    assert result == [Constants.TRAINING_REVIEW_CHOICE]


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
    assert len(result) == 1
    assert "TU SIGUIENTE MESOCICLO" in result[0]
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
@pytest.mark.parametrize("reason", ["preferencia", "no tengo dolor, prefiero otro ejercicio"])
async def test_swap_requires_selection_then_confirmation(collaborators: tuple, reason: str) -> None:
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
    result = await service.handle(7, f"/train cambiar 101 2 {reason}")
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
async def test_swap_clarification_resumes_with_request_local_equipment_filter(
    collaborators: tuple,
) -> None:
    service, repository, _, _, adaptation = collaborators
    flow = TrainingWorkflow(id=3, base_plan_id=10, kind="exercise_swap", state="reviewing")
    repository.start.return_value = flow
    repository.claim_generation.return_value = flow
    repository.get_workflow.return_value = flow
    question = "¿Te refieres a una barra de pesas?"
    adaptation.extract_swap_constraints.return_value = AdaptationReply(
        SwapConstraints(excluded_equipment=[], safety_hold=False, clarification=question),
        [],
    )
    assert await service.handle(7, "/train cambiar 101 2 no tengo barra") == [question]
    service._retriever.retrieve_alternatives.assert_not_awaited()
    assert await service.handle(7, "/train cambiar") == [question]
    adaptation.extract_swap_constraints.return_value = AdaptationReply(
        SwapConstraints(excluded_equipment=["barbell"], safety_hold=False, clarification=None),
        [],
    )
    service._retriever.retrieve_alternatives.return_value = []
    assert await service.handle(7, "Sí, barra de pesas") == [
        Constants.TRAINING_NO_ALTERNATIVES_MESSAGE
    ]
    assert question in flow.swap.reason
    assert "Sí, barra de pesas" in flow.swap.reason
    assert service._retriever.retrieve_alternatives.await_args.kwargs["excluded_equipment"] == [
        "barbell"
    ]
    adaptation.propose_swap.assert_not_awaited()


@pytest.mark.asyncio
async def test_pain_is_not_treated_by_swap(collaborators: tuple) -> None:
    service, repository, _, _, adaptation = collaborators
    repository.start.return_value = TrainingWorkflow(
        id=3, base_plan_id=10, kind="exercise_swap", state="reviewing"
    )
    repository.claim_generation.return_value = repository.start.return_value
    adaptation.extract_swap_constraints.return_value = AdaptationReply(
        SwapConstraints(excluded_equipment=[], safety_hold=True, clarification=None), []
    )
    assert await service.handle(7, "/train cambiar 101 2 dolor") == [
        Constants.TRAINING_SAFETY_MESSAGE
    ]
    adaptation.propose_swap.assert_not_awaited()


@pytest.mark.asyncio
async def test_interaction_reminder_persists_telegram_delay(collaborators: tuple) -> None:
    service, repository, _, _, _ = collaborators
    delivery = ReminderDelivery(1, 7, 22, 1)
    repository.reserve_interaction_reminder.return_value = delivery
    sender = AsyncMock(side_effect=RetryAfter(600))
    await service.remind_on_interaction(7, 22, sender)
    assert repository.finish_reminder.await_args.kwargs["retry_at"] == NOW + timedelta(seconds=600)
    assert not repository.finish_reminder.await_args.kwargs["failed"]
