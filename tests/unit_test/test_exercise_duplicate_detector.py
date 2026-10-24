from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.service.agent.exercise_duplicate_detector import ExerciseDuplicateDetector
from tests.unit_test.test_exercise_submission import proposal


@pytest.mark.asyncio
async def test_returns_semantically_similar_exercise() -> None:
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.1] * 384]
    repository = AsyncMock()
    match = ExerciseMatch(Exercise(id=7, name="weighted backpack row"), 0.05)
    repository.search_scored.return_value = [match]

    result = await ExerciseDuplicateDetector(embedder, repository).find(proposal())

    assert result == match
    repository.search_scored.assert_awaited_once_with([0.1] * 384, top_k=5)


@pytest.mark.asyncio
async def test_ignores_distant_exercise() -> None:
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.1] * 384]
    repository = AsyncMock()
    repository.search_scored.return_value = [
        ExerciseMatch(Exercise(id=8, name="barbell bench press"), 0.2)
    ]

    result = await ExerciseDuplicateDetector(embedder, repository).find(proposal())

    assert result is None
