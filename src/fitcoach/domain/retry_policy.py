"""Retry rules shared by the scheduled Telegram deliveries."""

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    retry_delay: timedelta
    retry_max_delay: timedelta
    sending_timeout: timedelta
    batch_size: int

    def delay_after(self, attempts: int) -> timedelta:
        # Doubles per attempt; same formula the reminders used: 30 * 2**attempts, capped.
        return min(self.retry_max_delay, self.retry_delay * (1 << attempts))

    def exhausted(self, attempts: int) -> bool:
        return attempts >= self.max_attempts
