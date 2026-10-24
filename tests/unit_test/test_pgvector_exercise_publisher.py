from unittest.mock import AsyncMock, MagicMock

import pytest

from fitcoach.infrastructure.vectordb.models import (
    ExercisePublicationRecord,
    ExerciseRecord,
)
from fitcoach.infrastructure.vectordb.pgvector_exercise_publisher import (
    PgVectorExercisePublisher,
)
from tests.unit_test.test_exercise_moderation_service import proposal


@pytest.mark.asyncio
async def test_existing_publication_is_idempotent() -> None:
    session = MagicMock()
    session.get = AsyncMock(
        return_value=ExercisePublicationRecord(submission_id=12, exercise_id=5000)
    )

    result = await PgVectorExercisePublisher(session).publish(12, proposal(), [0.1] * 384)

    assert result == 5000
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_inserts_exercise_and_publication_in_one_transaction() -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)

    async def flush() -> None:
        exercise = session.add.call_args_list[0].args[0]
        exercise.id = 5001

    session.flush = AsyncMock(side_effect=flush)
    session.commit = AsyncMock()

    result = await PgVectorExercisePublisher(session).publish(12, proposal(), [0.1] * 384)

    exercise = session.add.call_args_list[0].args[0]
    publication = session.add.call_args_list[1].args[0]
    assert isinstance(exercise, ExerciseRecord)
    assert exercise.metadata_vector == [0.1] * 384
    assert isinstance(publication, ExercisePublicationRecord)
    assert publication.submission_id == 12
    assert publication.exercise_id == 5001
    assert result == 5001
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejects_embedding_with_wrong_dimensions() -> None:
    session = MagicMock()

    with pytest.raises(ValueError, match="384"):
        await PgVectorExercisePublisher(session).publish(12, proposal(), [0.1])

    session.add.assert_not_called()
