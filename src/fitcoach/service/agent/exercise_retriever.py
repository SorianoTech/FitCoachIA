"""Retrieval step: profile -> embedded queries -> exercises from pgVector.

One query per muscle group rather than one for the whole plan: a single
"full body" query collapses into whatever the corpus considers average, and the
Trainer then has no chest options to pick from on chest day.
"""

import logging
from collections.abc import Sequence

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.ia.embedder_client import Embedder
from fitcoach.repository.exercise_repository import ExerciseRepository
from fitcoach.service.agent.rag_context import build_query_text, equipment_filter

logger = logging.getLogger(__name__)

# Coverage of the corpus's muscle_group values, enough to build a split for any
# of the three goals.
MUSCLE_GROUPS: tuple[str, ...] = (
    "chest",
    "back",
    "legs",
    "shoulders",
    "arms",
    "core",
    "cardio",
)


class ExerciseRetriever:
    def __init__(
        self,
        embedder: Embedder,
        exercise_repository: ExerciseRepository,
        top_k: int = 8,
        muscle_groups: Sequence[str] = MUSCLE_GROUPS,
    ) -> None:
        self._embedder = embedder
        self._exercise_repository = exercise_repository
        self._top_k = top_k
        self._muscle_groups = tuple(muscle_groups)

    async def retrieve(self, profile: InterviewerProfile) -> list[Exercise]:
        """Top-k exercises per muscle group, de-duplicated, order preserved."""
        queries = [build_query_text(profile, group) for group in self._muscle_groups]
        vectors = await self._embedder.embed(queries)
        equipment = equipment_filter(profile)

        retrieved: dict[int, Exercise] = {}
        for group, vector in zip(self._muscle_groups, vectors, strict=True):
            exercises = await self._exercise_repository.search(
                query_vector=vector, top_k=self._top_k, equipment=equipment
            )
            logger.debug("muscle_group=%s retrieved=%s", group, len(exercises))
            for exercise in exercises:
                retrieved.setdefault(exercise.id, exercise)
        return list(retrieved.values())
