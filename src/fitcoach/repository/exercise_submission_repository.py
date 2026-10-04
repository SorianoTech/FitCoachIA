from collections.abc import Sequence
from typing import Protocol

from fitcoach.domain.exercise_submission import (
    ExerciseProposal,
    ExerciseSubmission,
    ExerciseSubmissionStatus,
)


class ExerciseSubmissionRepository(Protocol):
    async def create(
        self,
        chat_id: int,
        message_thread_id: int | None,
        raw_description: str,
        proposal: ExerciseProposal | None,
        model: str,
        duplicate_exercise_id: int | None = None,
    ) -> ExerciseSubmission: ...

    async def get(self, submission_id: int) -> ExerciseSubmission | None: ...

    async def get_draft(self, chat_id: int) -> ExerciseSubmission | None: ...

    async def list_pending(self, limit: int = 20) -> Sequence[ExerciseSubmission]: ...

    async def update_draft(
        self,
        chat_id: int,
        raw_description: str,
        proposal: ExerciseProposal | None,
        duplicate_exercise_id: int | None = None,
    ) -> ExerciseSubmission: ...

    async def set_status(
        self,
        submission_id: int,
        expected: ExerciseSubmissionStatus,
        status: ExerciseSubmissionStatus,
        *,
        reviewed_by: int | None = None,
        moderation_notes: str | None = None,
        published_exercise_id: int | None = None,
    ) -> ExerciseSubmission: ...
