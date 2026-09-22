"""Semantic search over the exercises corpus.

Cheap SQL prefilter first (equipment the user actually has), semantic ordering
within whatever survives. Doing it the other way round would rank the whole
catalogue and then throw away most of it, and an HNSW scan is the expensive
half.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.exercise import Exercise
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
    ) -> list[Exercise]:
        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionError(
                f"Query vector has {len(query_vector)} dimensions, "
                f"the corpus needs {EMBEDDING_DIMENSIONS}"
            )
        statement = select(ExerciseRecord)
        if equipment:
            statement = statement.where(ExerciseRecord.equipment.in_(list(equipment)))
        statement = statement.order_by(
            ExerciseRecord.metadata_vector.cosine_distance(list(query_vector))
        ).limit(top_k)

        records = list((await self._session.scalars(statement)).all())
        logger.debug(
            "Retrieved %s exercises (top_k=%s, equipment=%s)", len(records), top_k, equipment
        )
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_domain(record: ExerciseRecord) -> Exercise:
        return Exercise(
            id=record.id,
            name=record.name,
            category=record.category,
            body_part=record.body_part,
            equipment=record.equipment,
            muscle_group=record.muscle_group,
            target=record.target,
            secondary_muscles=list(record.secondary_muscles or []),
            instructions_en=record.instructions_en,
        )
