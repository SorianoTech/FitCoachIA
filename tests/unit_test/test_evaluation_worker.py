from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Bot
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from fitcoach.domain.constants import Constants
from fitcoach.domain.training_evaluation import MAX_SCORE
from fitcoach.infrastructure.config.settings import EvaluationSettings
from fitcoach.infrastructure.database.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from fitcoach.infrastructure.jobs import evaluation
from fitcoach.infrastructure.jobs.evaluation import poll_question, run_batch
from fitcoach.repository.evaluation_repository import EvaluationConflictError, EvaluationDelivery

_NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluation, "utc_now", lambda: _NOW)


def _settings(**values: object) -> EvaluationSettings:
    return EvaluationSettings(_env_file=None, enabled=True, **values)


def _delivery(
    attempts: int = 1, previous_message_id: int | None = None, goal: str | None = "gain_muscle"
) -> EvaluationDelivery:
    return EvaluationDelivery(
        id=1,
        chat_id=7,
        thread_id=22,
        week_number=2,
        goal=goal,
        attempts=attempts,
        previous_message_id=previous_message_id,
    )


def _repository(*deliveries: EvaluationDelivery) -> AsyncMock:
    repository = AsyncMock(spec=PostgresEvaluationRepository)
    repository.claim.side_effect = [*deliveries, None]
    return repository


def _bot() -> AsyncMock:
    bot = AsyncMock(spec=Bot)
    bot.send_poll.return_value = MagicMock(message_id=555, poll=MagicMock(id="poll-1"))
    return bot


# --- poll texts ---------------------------------------------------------------


class TestPollTexts:
    def test_the_question_names_the_week_and_the_goal(self) -> None:
        assert (
            poll_question(2, "gain_muscle")
            == "Semana 2 de tu plan para ganar músculo: ¿qué te está pareciendo?"
        )

    @pytest.mark.parametrize("goal", [None, "unknown_goal"])
    def test_without_a_known_goal_the_question_stays_generic(self, goal: str | None) -> None:
        assert poll_question(3, goal) == "Semana 3 de tu plan: ¿qué te está pareciendo?"

    def test_there_is_one_option_per_score(self) -> None:
        options = Constants.EVALUATION_POLL_OPTIONS

        assert len(options) == MAX_SCORE + 1
        assert [option.split(" - ")[0] for option in options] == [
            str(score) for score in range(MAX_SCORE + 1)
        ]
        assert options[0] == "0 - No me ha gustado nada"
        assert options[-1] == "5 - Lo recomiendo sin dudar"


# --- run_batch ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_worker_does_not_claim() -> None:
    repository = _repository()

    assert await run_batch(repository, _bot(), EvaluationSettings(_env_file=None)) == 0

    repository.claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_sends_a_non_anonymous_poll_to_the_cycle_thread() -> None:
    delivery = _delivery()
    repository = _repository(delivery)
    bot = _bot()

    assert await run_batch(repository, bot, _settings()) == 1

    kwargs = bot.send_poll.await_args.kwargs
    assert kwargs["chat_id"] == 7
    assert kwargs["message_thread_id"] == 22
    assert kwargs["question"] == poll_question(2, "gain_muscle")
    assert list(kwargs["options"]) == list(Constants.EVALUATION_POLL_OPTIONS)
    assert kwargs["is_anonymous"] is False
    assert kwargs["allows_multiple_answers"] is False
    # The first vote is final: the user cannot change or retract it.
    assert kwargs["allows_revoting"] is False
    repository.mark_sent.assert_awaited_once_with(delivery, "poll-1", 555, _NOW)


@pytest.mark.asyncio
async def test_closes_the_previous_unanswered_poll_before_sending() -> None:
    repository = _repository(_delivery(previous_message_id=1001))
    bot = _bot()

    await run_batch(repository, bot, _settings())

    bot.stop_poll.assert_awaited_once_with(chat_id=7, message_id=1001)
    calls = [name for name, *_ in bot.mock_calls if name in ("stop_poll", "send_poll")]
    assert calls == ["stop_poll", "send_poll"]


@pytest.mark.asyncio
async def test_nothing_is_closed_without_a_previous_unanswered_poll() -> None:
    bot = _bot()

    await run_batch(_repository(_delivery()), bot, _settings())

    bot.stop_poll.assert_not_awaited()


@pytest.mark.asyncio
async def test_failing_to_close_the_previous_poll_does_not_block_the_new_one() -> None:
    repository = _repository(_delivery(previous_message_id=1001))
    bot = _bot()
    bot.stop_poll.side_effect = BadRequest("Poll has already been closed")

    assert await run_batch(repository, bot, _settings()) == 1

    bot.send_poll.assert_awaited_once()
    repository.mark_sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_claim_uses_the_configured_sending_timeout() -> None:
    repository = _repository()

    await run_batch(repository, _bot(), _settings(sending_timeout_seconds=60))

    repository.claim.assert_awaited_once_with(_NOW, timedelta(seconds=60))


@pytest.mark.asyncio
async def test_batch_stops_at_the_configured_size() -> None:
    repository = AsyncMock(spec=PostgresEvaluationRepository)
    repository.claim.side_effect = lambda *_: _delivery()

    assert await run_batch(repository, _bot(), _settings(batch_size=2)) == 2

    assert repository.claim.await_count == 2


@pytest.mark.asyncio
async def test_rate_limit_reschedules_the_poll() -> None:
    delivery = _delivery()
    repository = _repository(delivery)
    bot = _bot()
    bot.send_poll.side_effect = RetryAfter(30)

    assert await run_batch(repository, bot, _settings()) == 0

    repository.finish.assert_awaited_once_with(
        delivery, retry_at=_NOW + timedelta(seconds=30), failed=False
    )
    repository.mark_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_blocked_bot_marks_the_poll_failed() -> None:
    delivery = _delivery()
    repository = _repository(delivery)
    bot = _bot()
    bot.send_poll.side_effect = Forbidden("bot was blocked by the user")

    assert await run_batch(repository, bot, _settings()) == 0

    repository.finish.assert_awaited_once_with(delivery, retry_at=None, failed=True)


@pytest.mark.asyncio
async def test_exhausted_delivery_after_an_interruption_is_not_sent() -> None:
    delivery = _delivery(attempts=4)
    repository = _repository(delivery)
    bot = _bot()

    await run_batch(repository, bot, _settings(max_attempts=3))

    bot.send_poll.assert_not_awaited()
    repository.finish.assert_awaited_once_with(delivery, failed=True)


@pytest.mark.asyncio
async def test_unexpected_telegram_error_is_recorded_and_propagated() -> None:
    delivery = _delivery()
    repository = _repository(delivery)
    bot = _bot()
    bot.send_poll.side_effect = TelegramError("boom")

    with pytest.raises(TelegramError):
        await run_batch(repository, bot, _settings())

    repository.finish.assert_awaited_once_with(delivery, retry_at=None, failed=True)


@pytest.mark.asyncio
async def test_a_lock_lost_after_sending_is_propagated() -> None:
    repository = _repository(_delivery())
    repository.mark_sent.side_effect = EvaluationConflictError("lock expired")

    with pytest.raises(EvaluationConflictError):
        await run_batch(repository, _bot(), _settings())
