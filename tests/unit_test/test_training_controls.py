from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from telegram import Bot, Update

from fitcoach.domain.constants import Constants
from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.training_lifecycle import TrainingWorkflow
from fitcoach.service.conversation_service import ConversationService
from fitcoach.service.training_controls import training_keyboard
from fitcoach.service.training_service import TrainingService

pytest_plugins = ["tests.unit_test.test_training_service"]


def test_draft_buttons_include_identity_revision_and_fit_telegram_limit() -> None:
    from fitcoach.domain.trainer_plan import TrainingPlan
    from tests.unit_test.conftest import build_plan_payload

    workflow = TrainingWorkflow(
        id=42,
        revision=8,
        kind="renewal",
        base_plan_id=10,
        state="awaiting_confirmation",
        draft=TrainingPlan.model_validate(build_plan_payload()),
    )
    keyboard = training_keyboard(workflow, ["draft"])
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "Empezar hoy"
    assert keyboard.inline_keyboard[0][0].callback_data == "tr:accept:42:8"
    assert all(
        len(button.callback_data.encode()) <= 64
        for row in keyboard.inline_keyboard
        for button in row
    )


@pytest.mark.asyncio
async def test_accept_button_needs_current_revision(collaborators: tuple) -> None:
    service, repository, conversation, _, _ = collaborators
    flow = repository.start.return_value
    flow.state = "awaiting_confirmation"
    flow.draft = conversation.get_current_plan.return_value.plan
    flow.revision = 3
    repository.get_workflow.return_value = flow
    assert await service.callback(7, "tr:accept:1:2") == [Constants.TRAINING_CALLBACK_INVALID]
    repository.accept.assert_not_awaited()
    assert await service.callback(7, "tr:accept:1:3") == [Constants.TRAINING_ACCEPTED_MESSAGE]
    repository.accept.assert_awaited_once_with(7, 1, service._clock(), expected_revision=3)


@pytest.mark.asyncio
async def test_date_choices_and_custom_date_are_persisted(collaborators: tuple) -> None:
    service, repository, conversation, _, _ = collaborators
    flow = repository.start.return_value
    flow.state = "awaiting_confirmation"
    flow.draft = conversation.get_current_plan.return_value.plan
    repository.get_workflow.return_value = flow
    assert await service.callback(7, "tr:dates:1:0") == [Constants.TRAINING_DATE_PICKER]
    assert flow.answers["date_request"] == "choose"
    assert await service.callback(7, "tr:date:1:0:other") == [Constants.TRAINING_DATE_INPUT]
    assert flow.answers["date_request"] == "input"
    await service.handle(7, "2026-10-10")
    repository.accept.assert_awaited_once_with(7, 1, datetime(2026, 10, 10, tzinfo=UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize(("value", "date"), [("tomorrow", "2026-10-02"), ("monday", "2026-10-05")])
async def test_quick_dates_accept_correct_start(
    collaborators: tuple, value: str, date: str
) -> None:
    service, repository, conversation, _, _ = collaborators
    flow = repository.start.return_value
    flow.state = "awaiting_confirmation"
    flow.draft = conversation.get_current_plan.return_value.plan
    repository.get_workflow.return_value = flow
    await service.callback(7, f"tr:date:1:0:{value}")
    repository.accept.assert_awaited_once_with(
        7, 1, datetime.fromisoformat(date).replace(tzinfo=UTC), expected_revision=0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["invalid", "tr:accept:x:0", "tr:accept:99:0", "tr:unknown:1:0"])
async def test_invalid_buttons_do_not_mutate(collaborators: tuple, data: str) -> None:
    service, repository, _, _, _ = collaborators
    repository.get_workflow.return_value = repository.start.return_value
    assert await service.callback(7, data) == [Constants.TRAINING_CALLBACK_INVALID]
    repository.accept.assert_not_awaited()
    repository.save.assert_not_awaited()


def _callback_update(user_id: int = 7, update_id: int = 1) -> Update:
    return Update.de_json({
        "update_id": update_id,
        "callback_query": {
            "id": "click-1",
            "chat_instance": "chat",
            "data": "tr:accept:1:3",
            "from": {"id": user_id, "is_bot": False, "first_name": "Ana"},
            "message": {
                "message_id": 22,
                "date": 0,
                "text": "draft",
                "message_thread_id": 55,
                "chat": {"id": 7, "type": "private"},
            },
        },
    })


@pytest.mark.asyncio
async def test_callback_is_acknowledged_and_consumed_buttons_are_removed() -> None:
    from datetime import timedelta

    repository = AsyncMock()
    repository.claim_update.return_value = True
    bot = AsyncMock(spec=Bot)
    training = AsyncMock(spec=TrainingService)
    training.callback.return_value = [Constants.TRAINING_ACCEPTED_MESSAGE]
    training.keyboard.return_value = None
    service = ConversationService(
        bot,
        AsyncMock(),
        repository,
        UsageLimits(1000, 800, timedelta(days=1)),
        training_service=training,
    )
    await service.handle_update(_callback_update())
    bot.answer_callback_query.assert_awaited_once_with("click-1")
    training.callback.assert_awaited_once_with(7, "tr:accept:1:3")
    bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=7, message_id=22, reply_markup=None
    )
    assert bot.send_message.await_args.kwargs["message_thread_id"] == 55


@pytest.mark.asyncio
async def test_other_user_cannot_confirm_private_chat_proposal() -> None:
    from datetime import timedelta

    repository = AsyncMock()
    bot = AsyncMock(spec=Bot)
    training = AsyncMock(spec=TrainingService)
    service = ConversationService(
        bot,
        AsyncMock(),
        repository,
        UsageLimits(1000, 800, timedelta(days=1)),
        training_service=training,
    )
    await service.handle_update(_callback_update(user_id=8))
    training.callback.assert_not_awaited()
    assert bot.answer_callback_query.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_closure_and_postponement_buttons(collaborators: tuple) -> None:
    service, repository, _, _, _ = collaborators
    workflow = repository.start.return_value
    repository.get_workflow.return_value = workflow
    markup = await service.keyboard(7, [Constants.TRAINING_CLOSURE_QUESTION])
    assert markup.inline_keyboard[0][0].callback_data == "tr:close:1:0"
    await service.callback(7, "tr:postpone:1:0")
    repository.postpone.assert_awaited_once()
    assert repository.postpone.await_args.args[1] == datetime(2026, 10, 8, tzinfo=UTC)
    workflow.state = "reviewing"
    await service.callback(7, "tr:close:1:0")
    repository.close_cycle.assert_awaited_once()


@pytest.mark.asyncio
async def test_discard_button_cancels_only_the_identified_workflow(collaborators: tuple) -> None:
    service, repository, _, _, _ = collaborators
    workflow = repository.start.return_value
    repository.get_workflow.return_value = workflow
    assert await service.callback(7, "tr:cancel:1:0") == [Constants.TRAINING_CANCELLED_MESSAGE]
    assert workflow.state == "cancelled"
    repository.cancel.assert_not_awaited()


@pytest.mark.asyncio
async def test_details_button_does_not_modify_or_activate_the_draft(collaborators: tuple) -> None:
    service, repository, conversation, _, _ = collaborators
    workflow = repository.start.return_value
    workflow.state = "awaiting_confirmation"
    workflow.draft = conversation.get_current_plan.return_value.plan
    workflow.report = "Detailed report"
    repository.get_workflow.return_value = workflow
    before = workflow.model_dump_json()
    messages = await service.callback(7, "tr:details:1:0")
    assert any("PLAN COMPLETO PROPUESTO" in text for text in messages)
    assert "TU SIGUIENTE MESOCICLO" in messages[-1]
    assert workflow.model_dump_json() == before
    repository.accept.assert_not_awaited()
    repository.save.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_duplicate_update_is_not_processed() -> None:
    from datetime import timedelta

    repository = AsyncMock()
    repository.claim_update.return_value = False
    bot = AsyncMock(spec=Bot)
    training = AsyncMock(spec=TrainingService)
    service = ConversationService(
        bot,
        AsyncMock(),
        repository,
        UsageLimits(1000, 800, timedelta(days=1)),
        training_service=training,
    )
    await service.handle_update(_callback_update())
    training.callback.assert_not_awaited()
    bot.edit_message_reply_markup.assert_not_awaited()
