from unittest.mock import AsyncMock

import pytest

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.domain.exercise_catalogue import canonical_group, catalogue_equipment
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.repository.exercise_repository import ExerciseRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever, available_equipment


def test_equipment_aliases_and_unknown_values() -> None:
    assert available_equipment(["mancuernas"]) == ["body weight", "dumbbell"]
    with pytest.raises(ValueError, match="clarification"):
        available_equipment(["todo el gimnasio"])


def test_band_aliases_do_not_merge_distinct_apparatus() -> None:
    assert available_equipment(["band", "bandas"]) == ["body weight", "resistance band"]
    assert catalogue_equipment(["resistance band"]) == ["band", "resistance band"]
    assert available_equipment(["ez barbell"]) == ["body weight", "ez barbell"]
    assert "barbell" not in catalogue_equipment(["ez barbell"])


def test_canonical_groups_are_derived_only_from_verified_targets() -> None:
    assert canonical_group("pectorals") == "chest"
    assert canonical_group("quads") == "legs"
    assert canonical_group("biceps") == "arms"
    assert canonical_group("unknown") is None


@pytest.mark.parametrize("distance", [-0.1, 2.1, float("nan"), float("inf")])
def test_match_rejects_invalid_distances(distance: float) -> None:
    with pytest.raises(ValueError, match="Cosine distance"):
        ExerciseMatch(Exercise(1, "press"), distance)


@pytest.mark.asyncio
async def test_alternatives_filter_same_target_material_and_source(
    profile: InterviewerProfile,
) -> None:
    embedder = AsyncMock()
    embedder.embed.return_value = [[0.1] * 384]
    repository = AsyncMock(spec=ExerciseRepository)
    source = Exercise(1, "press", equipment="barbell", muscle_group="chest", target="pectorals")
    valid = Exercise(
        2, "other press", equipment="barbell", muscle_group="triceps", target="pectorals"
    )
    candidates = [
        source,
        valid,
        Exercise(3, "row", equipment="barbell", muscle_group="back", target="lats"),
        Exercise(4, "cable press", equipment="cable", muscle_group="chest", target="pectorals"),
    ]
    repository.search_scored.return_value = [ExerciseMatch(item, 0.2) for item in candidates]
    result = await ExerciseRetriever(embedder, repository).retrieve_alternatives(
        profile, source, "preferencia"
    )
    assert result == [valid]
    assert repository.search_scored.await_args.kwargs["target"] == "pectorals"
    assert repository.search_scored.await_args.kwargs["excluded_ids"] == [1]
    assert "muscle_group" not in repository.search_scored.await_args.kwargs


@pytest.mark.asyncio
async def test_missing_target_cannot_be_substituted(profile: InterviewerProfile) -> None:
    retriever = ExerciseRetriever(AsyncMock(), AsyncMock(spec=ExerciseRepository))
    with pytest.raises(ValueError, match="primary target"):
        await retriever.retrieve_alternatives(profile, Exercise(1, "unknown"), "cambio")
