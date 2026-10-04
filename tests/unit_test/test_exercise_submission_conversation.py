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
    submissions.handle = AsyncMock(
        return_value=ExerciseSubmissionReply(["Respuesta curator"], [])
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
