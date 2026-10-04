from typing import Protocol

from fitcoach.domain.exercise_submission import ExerciseProposal


class ExercisePublisher(Protocol):
    async def publish(
        self,
        submission_id: int,
        proposal: ExerciseProposal,
        embedding: list[float],
    ) -> int: ...
