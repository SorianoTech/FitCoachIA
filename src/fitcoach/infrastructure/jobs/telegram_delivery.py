"""How a scheduled delivery reacts to a failed Telegram call, shared by the workers."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError

from fitcoach.domain.retry_policy import RetryPolicy

_MIN_RATE_LIMIT_DELAY = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class FailureOutcome:
    retry_at: datetime | None
    failed: bool
    # Not a known Telegram failure: the worker stops so it gets noticed.
    unexpected: bool = False


def classify_failure(
    error: TelegramError, attempts: int, policy: RetryPolicy, now: datetime
) -> FailureOutcome:
    # BadRequest subclasses NetworkError, so it must be checked first.
    if isinstance(error, BadRequest | Forbidden):
        return FailureOutcome(retry_at=None, failed=True)
    if isinstance(error, RetryAfter):
        delay = max(_MIN_RATE_LIMIT_DELAY, _as_timedelta(error.retry_after))
        return FailureOutcome(retry_at=now + delay, failed=policy.exhausted(attempts))
    if isinstance(error, NetworkError):
        return FailureOutcome(
            retry_at=now + policy.delay_after(attempts), failed=policy.exhausted(attempts)
        )
    return FailureOutcome(retry_at=None, failed=True, unexpected=True)


def _as_timedelta(value: float | timedelta) -> timedelta:
    return value if isinstance(value, timedelta) else timedelta(seconds=value)
