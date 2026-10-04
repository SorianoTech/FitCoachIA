from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Bot, Update

from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.domain.token_usage import TokenUsage
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.service.agent.interviewer_chain import InterviewerChain
from fitcoach.service.conversation_service import ConversationService
from fitcoach.service.exercise_moderation_service import (
    ExerciseModerationNotification,
    ExerciseModerationReply,
    ExerciseModerationService,
)
from fitcoach.service.exercise_submission_service import (
    ExerciseSubmissionReply,
    ExerciseSubmissionService,
)
from fitcoach.service.training_service import TrainingService


def update(text: str) -> Update:
    return Update.de_json({
        "update_id": 10,
        "message": {
            "message_id": 20,
            "date": 0,
            "chat": {"id": 7, "type": "private"},
            "text": text,
        },
    })


def admin_update(text: str) -> Update:
    return Update.de_json({
        "update_id": 11,
        "message": {
            "message_id": 21,
            "date": 0,
            "chat": {"id": 9, "type": "private"},
            "from": {"id": 9, "is_bot": False, "first_name": "Admin"},
            "text": text,
        },
    })


def exercise_callback(data: str = "ex:confirm:12") -> Update:
    return Update.de_json({
        "update_id": 12,
        "callback_query": {
            "id": "exercise-click",
            "chat_instance": "chat",
            "data": data,
            "from": {"id": 7, "is_bot": False, "first_name": "User"},
            "message": {
                "message_id": 22,
                "date": 0,
                "chat": {"id": 7, "type": "private"},
                "text": "Si la propuesta es correcta...",
            },
        },
    })


def service(
    *,
    tokens_used: int = 0,
) -> tuple[ConversationService, AsyncMock, AsyncMock, MagicMock]:
    bot = AsyncMock(spec=Bot)
    interviewer = AsyncMock(spec=InterviewerChain)
    conversations = AsyncMock(spec=ConversationRepository)
    conversations.claim_update.return_value = True
    conversations.tokens_used_since.return_value = tokens_used
    submissions = MagicMock(spec=ExerciseSubmissionService)
    submissions.has_draft = AsyncMock(return_value=False)
    submissions.will_invoke_model = AsyncMock(return_value=False)
    submissions.handle = AsyncMock(return_value=ExerciseSubmissionReply(["Respuesta curator"], []))
    submissions.handle_callback = AsyncMock(
        return_value=ExerciseSubmissionReply(["Propuesta enviada a moderación."], [])
    )
    subject = ConversationService(
        bot,
        interviewer,
        conversations,
        UsageLimits(hard_tokens=100, soft_tokens=50, window=timedelta(days=1)),
        exercise_submissions=submissions,
    )
    return subject, bot, conversations, submissions


@pytest.mark.asyncio
async def test_add_exercise_command_is_routed_to_submission_flow() -> None:
    subject, bot, _, submissions = service()

    await subject.handle_update(update("/add_exercise remo con mochila"))

    submissions.handle.assert_awaited_once_with(
        7, None, "/add_exercise remo con mochila", command=True
    )
    bot.send_message.assert_awaited_once_with(
        chat_id=7, message_thread_id=None, text="Respuesta curator"
    )


@pytest.mark.asyncio
async def test_explicit_natural_intent_is_routed_without_hijacking_other_messages() -> None:
    subject, _, _, submissions = service()
    submissions.is_natural_intent.side_effect = lambda text: text.startswith("Quiero añadir")

    await subject.handle_update(update("Quiero añadir un ejercicio nuevo"))

    submissions.handle.assert_awaited_once_with(
        7, None, "Quiero añadir un ejercicio nuevo", command=False
    )


@pytest.mark.asyncio
async def test_model_call_obeys_hard_quota_but_confirmation_can_remain_free() -> None:
    subject, bot, _, submissions = service(tokens_used=100)
    submissions.has_draft.return_value = True
    submissions.will_invoke_model.return_value = True

    await subject.handle_update(update("Añado más detalles"))

    submissions.handle.assert_not_awaited()
    assert "límite de uso" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_curator_token_usage_is_recorded_under_its_agent() -> None:
    subject, _, conversations, submissions = service()
    submissions.handle.return_value = ExerciseSubmissionReply(
        ["Propuesta"],
        [TokenUsage("curator-model", 10, 5, 15, latency_ms=20)],
        True,
    )

    await subject.handle_update(update("/add_exercise remo"))

    conversations.record_token_usage.assert_awaited_once()
    assert conversations.record_token_usage.await_args.kwargs["agent"] == "exercise_curator"
    assert conversations.record_token_usage.await_args.kwargs["model"] == "curator-model"


@pytest.mark.asyncio
async def test_generated_proposal_adds_confirmation_keyboard_to_last_message() -> None:
    subject, bot, _, submissions = service()
    submissions.handle.return_value = ExerciseSubmissionReply(
        ["Propuesta", "Confirma o cancela"],
        [],
        confirmation_submission_id=12,
    )

    await subject.handle_update(update("/add_exercise remo"))

    calls = bot.send_message.await_args_list
    assert "reply_markup" not in calls[0].kwargs
    keyboard = calls[1].kwargs["reply_markup"]
    assert keyboard.inline_keyboard[0][0].callback_data == "ex:confirm:12"
    assert keyboard.inline_keyboard[0][1].callback_data == "ex:cancel:12"


@pytest.mark.asyncio
async def test_exercise_callback_is_acknowledged_and_retires_keyboard() -> None:
    subject, bot, _, submissions = service()

    await subject.handle_update(exercise_callback())

    submissions.handle_callback.assert_awaited_once_with(7, 12, "confirm")
    bot.answer_callback_query.assert_awaited_once_with("exercise-click")
    bot.edit_message_reply_markup.assert_awaited_once_with(
        chat_id=7,
        message_id=22,
        reply_markup=None,
    )
    bot.send_message.assert_awaited_once_with(
        chat_id=7,
        message_thread_id=None,
        text="Propuesta enviada a moderación.",
    )


@pytest.mark.asyncio
async def test_stale_exercise_callback_is_reported_as_an_alert() -> None:
    subject, bot, _, submissions = service()
    submissions.handle_callback.return_value = ExerciseSubmissionReply(
        ["Esta propuesta ya no está disponible. Usa /add_exercise para consultar o crear otra."],
        [],
        callback_valid=False,
    )

    await subject.handle_update(exercise_callback())

    assert bot.answer_callback_query.await_args.kwargs["show_alert"] is True
    bot.edit_message_reply_markup.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_misspelled_admin_command_never_reaches_draft_or_training_workflows() -> None:
    bot = AsyncMock(spec=Bot)
    conversations = AsyncMock(spec=ConversationRepository)
    conversations.claim_update.return_value = True
    submissions = MagicMock(spec=ExerciseSubmissionService)
    submissions.has_draft = AsyncMock(return_value=True)
    training = AsyncMock(spec=TrainingService)
    training.has_workflow.return_value = True
    subject = ConversationService(
        bot,
        AsyncMock(spec=InterviewerChain),
        conversations,
        UsageLimits(hard_tokens=100, soft_tokens=50, window=timedelta(days=1)),
        training_service=training,
        exercise_submissions=submissions,
    )

    await subject.handle_update(update("/approve_excercise 12"))

    submissions.has_draft.assert_not_awaited()
    submissions.handle.assert_not_awaited()
    training.has_workflow.assert_not_awaited()
    training.handle.assert_not_awaited()
    assert bot.send_message.await_args.kwargs["text"] == (
        "No reconozco el comando «/approve_excercise». Quizá quisiste usar /approve_exercise."
    )


@pytest.mark.asyncio
async def test_moderation_command_uses_actor_user_id_and_notifies_submitter() -> None:
    bot = AsyncMock(spec=Bot)
    conversations = AsyncMock(spec=ConversationRepository)
    conversations.claim_update.return_value = True
    moderation = AsyncMock(spec=ExerciseModerationService)
    moderation.handle.return_value = ExerciseModerationReply(
        ["Aprobada"],
        ExerciseModerationNotification(77, 5, "Tu propuesta ha sido aprobada."),
    )
    subject = ConversationService(
        bot,
        AsyncMock(spec=InterviewerChain),
        conversations,
        UsageLimits(hard_tokens=100, soft_tokens=50, window=timedelta(days=1)),
        exercise_moderation=moderation,
    )

    await subject.handle_update(admin_update("/approve_exercise 12"))

    moderation.handle.assert_awaited_once_with(9, "/approve_exercise 12")
    assert bot.send_message.await_args_list[0].kwargs["chat_id"] == 9
    assert bot.send_message.await_args_list[1].kwargs == {
        "chat_id": 77,
        "message_thread_id": 5,
        "text": "Tu propuesta ha sido aprobada.",
    }
