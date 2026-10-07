from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from telegram import Bot, Update

from fitcoach.domain.rate_limiter import UsageLimits
from fitcoach.repository.conversation_repository import ConversationRepository
from fitcoach.repository.evaluation_repository import EvaluationRepository
from fitcoach.service.conversation_service import ConversationService

_LIMITS = UsageLimits(hard_tokens=1_000_000, soft_tokens=900_000, window=timedelta(hours=24))


def _poll_answer(option_ids: list[int], user_id: int | None = 7) -> Update:
    answer: dict[str, object] = {
        "poll_id": "poll-1",
        "option_ids": option_ids,
        # Required by Bot API 9.6 (python-telegram-bot >= 22.8).
        "option_persistent_ids": [f"option-{option}" for option in option_ids],
    }
    if user_id is None:
        answer["voter_chat"] = {"id": -100, "type": "channel"}
    else:
        answer["user"] = {"id": user_id, "is_bot": False, "first_name": "Ana"}
    return Update.de_json({"update_id": 99, "poll_answer": answer})


@pytest.fixture
def evaluations() -> AsyncMock:
    repository = AsyncMock(spec=EvaluationRepository)
    repository.record_answer.return_value = True
    return repository


@pytest.fixture
def bot() -> AsyncMock:
    return AsyncMock(spec=Bot)


@pytest.fixture
def conversation() -> AsyncMock:
    repository = AsyncMock(spec=ConversationRepository)
    repository.claim_update.return_value = True
    return repository


def _service(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock | None
) -> ConversationService:
    return ConversationService(
        bot=bot,
        interviewer=AsyncMock(),
        conversation_repository=conversation,
        usage_limits=_LIMITS,
        evaluation_repository=evaluations,
    )


@pytest.mark.asyncio
async def test_a_vote_is_stored_with_its_score_and_voter(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    await _service(bot, conversation, evaluations).handle_update(_poll_answer([4]))

    poll_id, user_id, score, _ = evaluations.record_answer.await_args.args
    assert (poll_id, user_id, score) == ("poll-1", 7, 4)


@pytest.mark.asyncio
async def test_a_retracted_vote_clears_the_score(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    await _service(bot, conversation, evaluations).handle_update(_poll_answer([]))

    assert evaluations.record_answer.await_args.args[2] is None


@pytest.mark.asyncio
async def test_the_bot_does_not_reply_to_a_vote(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    await _service(bot, conversation, evaluations).handle_update(_poll_answer([5]))

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_vote_for_an_unknown_poll_is_ignored_silently(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    evaluations.record_answer.return_value = False

    await _service(bot, conversation, evaluations).handle_update(_poll_answer([2]))

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_option_outside_the_scale_is_not_stored(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    await _service(bot, conversation, evaluations).handle_update(_poll_answer([6]))

    evaluations.record_answer.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_anonymous_voter_is_ignored(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    await _service(bot, conversation, evaluations).handle_update(_poll_answer([3], user_id=None))

    evaluations.record_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_without_an_evaluation_store_the_vote_is_ignored(
    bot: AsyncMock, conversation: AsyncMock
) -> None:
    await _service(bot, conversation, None).handle_update(_poll_answer([3]))

    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_redelivered_vote_is_not_stored_twice(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    conversation.claim_update.return_value = False

    await _service(bot, conversation, evaluations).handle_update(_poll_answer([3]))

    evaluations.record_answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_storage_failure_never_escapes_the_webhook(
    bot: AsyncMock, conversation: AsyncMock, evaluations: AsyncMock
) -> None:
    evaluations.record_answer.side_effect = RuntimeError("db down")

    await _service(bot, conversation, evaluations).handle_update(_poll_answer([3]))

    bot.send_message.assert_not_awaited()
