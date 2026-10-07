from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Protocol

from fitcoach.domain.scheduled_job import ClaimedJob, JobOutcome, JobType


class JobConflictError(RuntimeError):
    """The job is no longer locked by the scheduler that claimed it."""


class JobRepository(Protocol):
    async def claim(
        self, now: datetime, lock_timeout: timedelta, types: Collection[JobType]
    ) -> ClaimedJob | None: ...
    async def finish(self, job: ClaimedJob, outcome: JobOutcome, now: datetime) -> None: ...
