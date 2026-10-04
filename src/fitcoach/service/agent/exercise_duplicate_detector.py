"""Semantic duplicate detection for proposed catalogue exercises."""

from fitcoach.domain.exercise import ExerciseMatch
from fitcoach.domain.exercise_submission import ExerciseProposal, build_exercise_metadata_text
from fitcoach.infrastructure.ia.embedder_client import Embedder
from fitcoach.repository.exercise_repository import ExerciseRepository


class ExerciseDuplicateDetector:
    def __init__(
        self,
        embedder: Embedder,
        repository: ExerciseRepository,
        similarity_threshold: float = 0.92,
    ) -> None:
        if not 0 <= similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be between 0 and 1")
        self._embedder = embedder
        self._repository = repository
        self._similarity_threshold = similarity_threshold

    async def find(self, proposal: ExerciseProposal) -> ExerciseMatch | None:
        vectors = await self._embedder.embed([build_exercise_metadata_text(proposal)])
        matches = await self._repository.search_scored(vectors[0], top_k=5)
        normalized_name = proposal.name.casefold()
        return next(
            (
                match
                for match in matches
                if match.exercise.name.casefold() == normalized_name
                or match.similarity >= self._similarity_threshold
            ),
            None,
        )
