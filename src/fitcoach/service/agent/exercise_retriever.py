"""Retrieval step: profile -> embedded queries -> exercises from pgVector.

One query per muscle group rather than one for the whole plan: a single
"full body" query collapses into whatever the corpus considers average, and the
Trainer then has no chest options to pick from on chest day.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.domain.exercise_catalogue import (
    MUSCLE_TARGETS,
    available_equipment,
    canonical_group,
    known_equipment,
    normalize_equipment,
)
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.ia.embedder_client import Embedder
from fitcoach.infrastructure.observability.latency import latency_phase, timed
from fitcoach.repository.exercise_repository import ExerciseRepository
from fitcoach.service.agent.rag_context import build_query_text, equipment_filter

logger = logging.getLogger(__name__)

MUSCLE_GROUPS: tuple[str, ...] = tuple(MUSCLE_TARGETS)


@dataclass(frozen=True, slots=True)
class RetrievalGroup:
    group: str
    targets: tuple[str, ...]
    equipment: tuple[str, ...]
    matches: tuple[ExerciseMatch, ...]


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    groups: tuple[RetrievalGroup, ...]
    exercises: tuple[Exercise, ...]


class ExerciseRetriever:
    def __init__(
        self,
        embedder: Embedder,
        exercise_repository: ExerciseRepository,
        top_k: int = 8,
        muscle_groups: Sequence[str] = MUSCLE_GROUPS,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if any(group not in MUSCLE_TARGETS for group in muscle_groups):
            raise ValueError("Unknown muscle group")
        self._embedder = embedder
        self._exercise_repository = exercise_repository
        self._top_k = top_k
        self._muscle_groups = tuple(muscle_groups)

    @timed("retrieval")
    async def retrieve(self, profile: InterviewerProfile) -> list[Exercise]:
        """Top-k exercises per muscle group, de-duplicated, order preserved."""
        result = await self.retrieve_traced(profile)
        return list(result.exercises)

    async def retrieve_traced(self, profile: InterviewerProfile) -> RetrievalTrace:
        """Request-local rankings; no profile, query text or vectors in telemetry."""
        queries = [build_query_text(profile, group) for group in self._muscle_groups]
        with latency_phase("embeddings"):
            vectors = await self._embedder.embed(queries)
        equipment = equipment_filter(profile)

        retrieved: dict[int, Exercise] = {}
        traces = []
        for group, vector in zip(self._muscle_groups, vectors, strict=True):
            targets = tuple(sorted(MUSCLE_TARGETS[group]))
            matches = await self._exercise_repository.search_scored(
                query_vector=vector, top_k=self._top_k, equipment=equipment, targets=targets
            )
            traces.append(RetrievalGroup(group, targets, tuple(equipment), tuple(matches)))
            self._log_ranking(group, matches)
            for match in matches:
                exercise = match.exercise
                retrieved.setdefault(exercise.id, exercise)
        return RetrievalTrace(tuple(traces), tuple(retrieved.values()))

    @staticmethod
    def _log_ranking(group: str, matches: Sequence[ExerciseMatch]) -> None:
        logger.info(
            "RAG ranking group=%s count=%s distance_min=%s distance_max=%s",
            group,
            len(matches),
            min((item.distance for item in matches), default=None),
            max((item.distance for item in matches), default=None),
        )
        if not matches:
            logger.warning("RAG catalogue has no eligible exercise for group=%s", group)

    @timed("catalogue")
    async def get_by_ids(self, ids: Sequence[int]) -> list[Exercise]:
        return await self._exercise_repository.get_by_ids(ids)

    @timed("retrieval", action="exercise_swap")
    async def retrieve_alternatives(
        self,
        profile: InterviewerProfile,
        source: Exercise,
        reason: str,
        excluded_equipment: Sequence[str] = (),
    ) -> list[Exercise]:
        """Same target first: a broad group alone does not imply equivalence."""
        if not source.target:
            raise ValueError("The source exercise has no verified primary target")
        excluded = {normalize_equipment(item) for item in excluded_equipment}
        if not excluded.issubset(known_equipment()):
            raise ValueError("Unknown excluded equipment")
        equipment = [
            item for item in available_equipment(profile.training.equipment) if item not in excluded
        ]
        if not equipment:
            return []
        query = (
            f"name: {source.name} | muscle_group: {canonical_group(source.target) or ''} "
            f"| target: {source.target} | equipment: {', '.join(equipment)}"
            f" | variation: {reason}"
        )
        with latency_phase("embeddings"):
            vectors = await self._embedder.embed([query])
        if len(vectors) != 1:
            raise ValueError("The embedder must return exactly one variation vector")
        matches = await self._exercise_repository.search_scored(
            vectors[0],
            top_k=self._top_k,
            equipment=equipment,
            target=source.target,
            excluded_ids=[source.id],
        )
        self._log_ranking(canonical_group(source.target) or "unknown", matches)
        candidates = [match.exercise for match in matches]
        return [
            item
            for item in candidates
            if item.id != source.id
            and item.target == source.target
            and item.equipment is not None
            and normalize_equipment(item.equipment) in equipment
        ]
