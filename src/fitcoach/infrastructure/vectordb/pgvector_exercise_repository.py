"""Cosine ranking constrained by confirmed equipment and anatomical targets."""

import logging
import math
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.domain.exercise_catalogue import (
    canonical_group,
    catalogue_equipment,
    normalize_equipment,
)
from fitcoach.infrastructure.observability.latency import timed
from fitcoach.infrastructure.vectordb.models import EMBEDDING_DIMENSIONS, ExerciseRecord

logger = logging.getLogger(__name__)


class EmbeddingDimensionError(ValueError):
    """A query vector that cannot be compared against ``exercises.metadata_vector``."""


class PgVectorExerciseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query_vector: Sequence[float],
        top_k: int,
        equipment: Sequence[str] | None = None,
        muscle_group: str | None = None,
        target: str | None = None,
        excluded_ids: Sequence[int] = (),
        targets: Sequence[str] | None = None,
    ) -> list[Exercise]:
        matches = await self.search_scored(
            query_vector, top_k, equipment, muscle_group, target, excluded_ids, targets
        )
        return [match.exercise for match in matches]

    @timed("vector_search")
    async def search_scored(
        self,
        query_vector: Sequence[float],
        top_k: int,
        equipment: Sequence[str] | None = None,
        muscle_group: str | None = None,
        target: str | None = None,
        excluded_ids: Sequence[int] = (),
        targets: Sequence[str] | None = None,
    ) -> list[ExerciseMatch]:
        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionError(
                f"Query vector has {len(query_vector)} dimensions, "
                f"the corpus needs {EMBEDDING_DIMENSIONS}"
            )
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not all(math.isfinite(value) for value in query_vector) or not any(query_vector):
            raise ValueError("Query vector must be finite and nonzero")
        distance = ExerciseRecord.metadata_vector.cosine_distance(list(query_vector))
        statement = select(ExerciseRecord, distance.label("distance")).where(
            ExerciseRecord.metadata_vector.is_not(None)
        )
        if equipment is not None:
            statement = statement.where(
                ExerciseRecord.equipment.in_(catalogue_equipment(equipment))
            )
        if muscle_group:
            statement = statement.where(ExerciseRecord.muscle_group == muscle_group)
        if target:
            statement = statement.where(ExerciseRecord.target == target)
        if targets is not None:
            statement = statement.where(ExerciseRecord.target.in_(list(targets)))
        if excluded_ids:
            statement = statement.where(ExerciseRecord.id.not_in(list(excluded_ids)))
        statement = statement.order_by(distance, ExerciseRecord.id).limit(top_k)

        records = (await self._session.execute(statement)).all()
        logger.debug(
            "Retrieved %s exercises (top_k=%s, equipment=%s)", len(records), top_k, equipment
        )
        return [ExerciseMatch(self._to_domain(record), float(score)) for record, score in records]

    async def get_by_ids(self, ids: Sequence[int]) -> list[Exercise]:
        if not ids:
            return []
        records = await self._session.scalars(
            select(ExerciseRecord)
            .where(ExerciseRecord.id.in_(list(ids)))
            .order_by(ExerciseRecord.id)
        )
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_domain(record: ExerciseRecord) -> Exercise:
        return Exercise(
            id=record.id,
            name=record.name,
            category=record.category,
            body_part=record.body_part,
            equipment=normalize_equipment(record.equipment) if record.equipment else None,
            muscle_group=canonical_group(record.target),
            target=record.target,
            secondary_muscles=list(record.secondary_muscles or []),
            instructions_en=record.instructions_en,
        )
