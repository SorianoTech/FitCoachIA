from datetime import UTC, datetime, timedelta

import pytest

from fitcoach.domain.constants import Constants
from fitcoach.domain.trainer_plan import TrainingPlan
from fitcoach.domain.training_lifecycle import Mesocycle, TrainingWorkflow
from fitcoach.repository.conversation_repository import StoredTrainingPlan
from fitcoach.service.training_view import current_week, persistent_keyboard, view_plan
from tests.unit_test.conftest import build_plan_payload

pytest_plugins = ["tests.unit_test.test_training_service"]
START = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("days", "week"),
    [
        (-1, 1),
        (0, 1),
        (6, 1),
        (7, 2),
        (13, 2),
        (14, 3),
        (20, 3),
        (21, 4),
        (27, 4),
        (28, 4),
        (80, 4),
    ],
)
def test_calendar_boundaries(days: int, week: int) -> None:
    cycle = Mesocycle(id=1, started_at=START, expected_end_at=START + timedelta(days=28))
    actual, text = current_week(cycle, START + timedelta(days=days))
    assert actual == week
    if days < 0:
        assert "Vista anticipada" in text
    elif days >= 28:
        assert "Han pasado" in text
    else:
        assert "no ejecución registrada" in text


def test_missing_start_and_confirmed_closure_are_explicit() -> None:
    assert current_week(None, START)[0] is None
    cycle = Mesocycle(id=1, started_at=None, expected_end_at=None)
    assert current_week(cycle, START)[0] is None
    cycle.completed_at = START
    week, text = current_week(cycle, START)
    assert week == 4
    assert "cerrado por ti" in text


def test_week_shows_complete_prescription_without_draft_language() -> None:
    plan = TrainingPlan.model_validate(build_plan_payload())
    plan.weeks[1].days[0].exercises[0].notes = "Controla el movimiento"
    stored = StoredTrainingPlan(10, 3, plan, "report")
    cycle = Mesocycle(id=1, started_at=START, expected_end_at=START + timedelta(days=28))
    before = plan.model_dump_json()
    messages = view_plan(stored, cycle, START + timedelta(days=7), mode="week")
    text = "\n".join(messages)
    assert "Semana 2 prevista" in text
    assert "descanso 120s" in text
    assert "RPE" in text
    assert "Controla el movimiento" in text
    assert "SEMANA 1" not in text
    assert "borrador" not in text.lower()
    assert plan.model_dump_json() == before
    assert len(messages) == 5


@pytest.mark.asyncio
async def test_views_ignore_pending_workflow_and_quotas_without_llm(collaborators: tuple) -> None:
    service, repository, conversation, trainer, adaptation = collaborators
    repository.get_workflow.return_value = TrainingWorkflow(
        id=1,
        kind="renewal",
        base_plan_id=10,
        state="reviewing",
        answers={"clarification": "pending question"},
    )
    conversation.tokens_used_since.return_value = 9000
    for command in ("/train", "/train ver", "/train semana"):
        result = await service.handle(7, command)
        assert result[0].startswith("TU ")
        markup = await service.keyboard(7, result)
        assert markup.inline_keyboard[0][0].callback_data == "tv:10:current"
    await service.callback(7, "tv:10:week:2")
    repository.start.assert_not_awaited()
    repository.save.assert_not_awaited()
    repository.accept.assert_not_awaited()
    trainer.generate_next_plan.assert_not_awaited()
    adaptation.extract_review.assert_not_awaited()
    conversation.tokens_used_since.assert_not_awaited()


@pytest.mark.asyncio
async def test_resuming_pending_renewal_does_not_discard_draft(collaborators: tuple) -> None:
    service, repository, conversation, _, _ = collaborators
    plan = conversation.get_current_plan.return_value.plan
    flow = TrainingWorkflow(
        id=3,
        kind="renewal",
        base_plan_id=10,
        state="awaiting_confirmation",
        draft=plan,
        base_draft=plan,
    )
    repository.get_workflow.return_value = flow
    messages = await service.handle(7, "/train")
    markup = await service.keyboard(7, messages)
    assert markup.inline_keyboard[-1][0].callback_data == "tv:10:resume"
    assert "TU SIGUIENTE MESOCICLO" in (await service.callback(7, "tv:10:resume"))[0]
    assert flow.draft == plan
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data", ["tv:9:current", "tv:x:home", "tv:10:week:5", "tv:10:unknown", "tv:", "tv:10:review:1"]
)
async def test_stale_or_malformed_view_buttons_do_not_mutate(
    collaborators: tuple, data: str
) -> None:
    service, repository, _, _, _ = collaborators
    assert await service.callback(7, data) == [Constants.TRAINING_CALLBACK_INVALID]
    repository.start.assert_not_awaited()
    repository.save.assert_not_awaited()


def test_persistent_access_labels() -> None:
    keyboard = persistent_keyboard()
    assert keyboard.is_persistent
    assert keyboard.resize_keyboard
    assert keyboard.keyboard[0][0].text == Constants.TRAINING_NAVIGATION["week"]
