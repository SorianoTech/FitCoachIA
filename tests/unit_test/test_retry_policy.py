from datetime import timedelta

from fitcoach.domain.retry_policy import RetryPolicy

_POLICY = RetryPolicy(
    max_attempts=5,
    retry_delay=timedelta(seconds=30),
    retry_max_delay=timedelta(seconds=3600),
    sending_timeout=timedelta(seconds=120),
    batch_size=100,
)


class TestRetryPolicy:
    def test_delay_doubles_with_each_attempt(self) -> None:
        assert _POLICY.delay_after(1) == timedelta(seconds=60)
        assert _POLICY.delay_after(2) == timedelta(seconds=120)

    def test_delay_never_exceeds_the_maximum(self) -> None:
        assert _POLICY.delay_after(10) == timedelta(seconds=3600)

    def test_is_exhausted_when_attempts_reach_the_maximum(self) -> None:
        assert _POLICY.exhausted(5)

    def test_is_not_exhausted_below_the_maximum(self) -> None:
        assert not _POLICY.exhausted(4)
