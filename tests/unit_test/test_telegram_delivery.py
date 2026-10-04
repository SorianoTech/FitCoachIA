from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

from fitcoach.domain.retry_policy import RetryPolicy
from fitcoach.infrastructure.jobs.telegram_delivery import classify_failure

_NOW = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
_POLICY = RetryPolicy(
    max_attempts=5,
    retry_delay=timedelta(seconds=30),
    retry_max_delay=timedelta(seconds=3600),
    sending_timeout=timedelta(seconds=120),
    batch_size=100,
)


class TestRateLimit:
    def test_waits_what_telegram_asks(self) -> None:
        outcome = classify_failure(RetryAfter(5), 1, _POLICY, _NOW)

        assert outcome.retry_at == _NOW + timedelta(seconds=5)
        assert not outcome.failed
        assert not outcome.unexpected

    def test_waits_at_least_one_second(self) -> None:
        outcome = classify_failure(RetryAfter(0), 1, _POLICY, _NOW)

        assert outcome.retry_at == _NOW + timedelta(seconds=1)

    def test_fails_once_attempts_are_exhausted(self) -> None:
        assert classify_failure(RetryAfter(5), 5, _POLICY, _NOW).failed


class TestTransientFailure:
    @pytest.mark.parametrize("error", [NetworkError("offline"), TimedOut()])
    def test_retries_with_the_policy_delay(self, error: TelegramError) -> None:
        outcome = classify_failure(error, 1, _POLICY, _NOW)

        assert outcome.retry_at == _NOW + timedelta(seconds=60)
        assert not outcome.failed

    def test_the_delay_is_capped(self) -> None:
        policy = replace(_POLICY, retry_max_delay=timedelta(seconds=100))

        outcome = classify_failure(NetworkError("offline"), 4, policy, _NOW)

        assert outcome.retry_at == _NOW + timedelta(seconds=100)

    def test_fails_once_attempts_are_exhausted(self) -> None:
        assert classify_failure(NetworkError("offline"), 5, _POLICY, _NOW).failed


class TestPermanentFailure:
    @pytest.mark.parametrize("error", [BadRequest("chat not found"), Forbidden("blocked")])
    def test_fails_without_retry(self, error: TelegramError) -> None:
        outcome = classify_failure(error, 1, _POLICY, _NOW)

        assert outcome.failed
        assert outcome.retry_at is None
        assert not outcome.unexpected

    def test_an_unknown_telegram_error_fails_and_is_flagged(self) -> None:
        outcome = classify_failure(TelegramError("boom"), 1, _POLICY, _NOW)

        assert outcome.failed
        assert outcome.retry_at is None
        assert outcome.unexpected
