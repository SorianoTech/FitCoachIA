from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.exercise import Exercise
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.repository.exercise_repository import ExerciseRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever, available_equipment


def test_equipment_aliases_and_unknown_values() -> None:
    assert available_equipment(["mancuernas"]) == ["body weight", "dumbbell"]
    with pytest.raises(ValueError, match="clarification"):
        available_equipment(["todo el gimnasio"])


@pytest.mark.asyncio
async def test_alternatives_filter_same_target_material_and_source(
    profile: InterviewerProfile,
) -> None:
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.1] * 384]
    repository = AsyncMock(spec=ExerciseRepository)
    source = Exercise(1, "press", equipment="barbell", muscle_group="chest", target="pectorals")
    valid = Exercise(
        2, "other press", equipment="barbell", muscle_group="chest", target="pectorals"
    )
    repository.search.return_value = [
        source,
        valid,
        Exercise(3, "row", equipment="barbell", muscle_group="back", target="lats"),
        Exercise(4, "cable press", equipment="cable", muscle_group="chest", target="pectorals"),
    ]
    result = await ExerciseRetriever(embedder, repository).retrieve_alternatives(
        profile, source, "preferencia"
    )
    assert result == [valid]
    assert repository.search.await_args.kwargs["target"] == "pectorals"
    assert repository.search.await_args.kwargs["excluded_ids"] == [1]


@pytest.mark.asyncio
async def test_missing_target_cannot_be_substituted(profile: InterviewerProfile) -> None:
    retriever = ExerciseRetriever(AsyncMock(), AsyncMock(spec=ExerciseRepository))
    with pytest.raises(ValueError, match="primary target"):
        await retriever.retrieve_alternatives(profile, Exercise(1, "unknown"), "cambio")
