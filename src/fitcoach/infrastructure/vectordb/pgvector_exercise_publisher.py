"""Idempotent publication of moderated exercises into the vector catalogue."""

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fitcoach.domain.exercise_submission import ExerciseProposal
from fitcoach.infrastructure.vectordb.models import (
    EMBEDDING_DIMENSIONS,
    ExercisePublicationRecord,
    ExerciseRecord,
)


class PgVectorExercisePublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(
        self,
        submission_id: int,
        proposal: ExerciseProposal,
        embedding: list[float],
    ) -> int:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Embedding must have {EMBEDDING_DIMENSIONS} dimensions")
        existing = await self._session.get(ExercisePublicationRecord, submission_id)
        if existing is not None:
            return existing.exercise_id
        exercise = ExerciseRecord(
            name=proposal.name,
            category=proposal.category,
            body_part=proposal.body_part,
            equipment=proposal.equipment,
            muscle_group=proposal.muscle_group,
            target=proposal.target,
            secondary_muscles=proposal.secondary_muscles,
            instructions_en=proposal.instructions_en,
            instructions_tr=None,
            created_at=datetime.now(UTC),
            metadata_vector=embedding,
        )
        self._session.add(exercise)
        await self._session.flush()
        self._session.add(
            ExercisePublicationRecord(submission_id=submission_id, exercise_id=exercise.id)
        )
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = await self._session.get(ExercisePublicationRecord, submission_id)
            if existing is None:
                raise
            return existing.exercise_id
        return exercise.id
