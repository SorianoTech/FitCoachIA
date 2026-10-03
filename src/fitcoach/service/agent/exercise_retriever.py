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
from fitcoach.infrastructure.observability.latency import latency_phase, timed
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

    @timed("retrieval")
    async def retrieve(self, profile: InterviewerProfile) -> list[Exercise]:
        """Top-k exercises per muscle group, de-duplicated, order preserved."""
        logger.debug("profile=%s", profile)
        queries = [build_query_text(profile, group) for group in self._muscle_groups]
        logger.debug("queries=%s", queries)
        with latency_phase("embeddings"):
            vectors = await self._embedder.embed(queries)
        logger.debug("vectors=%s", vectors)
        equipment = equipment_filter(profile)
        logger.debug("equipment=%s", equipment)

        retrieved: dict[int, Exercise] = {}
        for group, vector in zip(self._muscle_groups, vectors, strict=True):
            exercises = await self._exercise_repository.search(
                query_vector=vector, top_k=self._top_k, equipment=equipment
            )
            logger.debug("muscle_group=%s retrieved=%s", group, len(exercises))
            for exercise in exercises:
                retrieved.setdefault(exercise.id, exercise)
        return list(retrieved.values())

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
        if any(item not in _KNOWN_EQUIPMENT for item in excluded_equipment):
            raise ValueError("Unknown excluded equipment")
        equipment = [
            item
            for item in available_equipment(profile.training.equipment)
            if item not in excluded_equipment
        ]
        if not equipment:
            return []
        query = (
            f"name: {source.name} | muscle_group: {source.muscle_group or ''} "
            f"| target: {source.target} | equipment: {', '.join(equipment)}"
            f" | variation: {reason}"
        )
        with latency_phase("embeddings"):
            vectors = await self._embedder.embed([query])
        if len(vectors) != 1:
            raise ValueError("The embedder must return exactly one variation vector")
        candidates = await self._exercise_repository.search(
            vectors[0],
            top_k=self._top_k,
            equipment=equipment,
            muscle_group=source.muscle_group,
            target=source.target,
            excluded_ids=[source.id],
        )
        return [
            item
            for item in candidates
            if item.id != source.id
            and item.target == source.target
            and (not source.muscle_group or item.muscle_group == source.muscle_group)
            and item.equipment in equipment
        ]


_EQUIPMENT_ALIASES = {
    "barra": "barbell",
    "mancuernas": "dumbbell",
    "mancuerna": "dumbbell",
    "bandas": "resistance band",
    "banda elastica": "resistance band",
    "peso corporal": "body weight",
    "polea": "cable",
    "poleas": "cable",
    "maquina smith": "smith machine",
}
_KNOWN_EQUIPMENT = {
    "barbell",
    "dumbbell",
    "body weight",
    "cable",
    "resistance band",
    "kettlebell",
    "stability ball",
    "smith machine",
    "leverage machine",
    "assisted",
    "weighted",
    "medicine ball",
    "bosu ball",
    "roller",
    "rope",
    "elliptical machine",
    "stationary bike",
    "skierg machine",
    "upper body ergometer",
    "trap bar",
}


def known_equipment() -> list[str]:
    return sorted(_KNOWN_EQUIPMENT)


def available_equipment(declared: Sequence[str]) -> list[str]:
    equipment = {"body weight"}
    for value in declared:
        normalized = _EQUIPMENT_ALIASES.get(value.lower().strip(), value.lower().strip())
        if normalized not in _KNOWN_EQUIPMENT:
            raise ValueError(f"Equipment needs clarification: {value}")
        equipment.add(normalized)
    return sorted(equipment)
