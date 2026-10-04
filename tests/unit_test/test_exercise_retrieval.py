from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fitcoach.domain.exercise import Exercise, ExerciseMatch
from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.vectordb.models import EMBEDDING_DIMENSIONS
from fitcoach.infrastructure.vectordb.pgvector_exercise_repository import (
    EmbeddingDimensionError,
    PgVectorExerciseRepository,
)
from fitcoach.repository.exercise_repository import ExerciseRepository
from fitcoach.service.agent.exercise_retriever import MUSCLE_GROUPS, ExerciseRetriever


def _vector() -> list[float]:
    return [0.1] * EMBEDDING_DIMENSIONS


def _session_returning(records: list[Any]) -> MagicMock:
    session = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = records
    session.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=[(record, 0.25) for record in records]))
    )
    return session


def _record(exercise_id: int = 1, **overrides: Any) -> MagicMock:
    record = MagicMock()
    record.id = exercise_id
    record.name = "barbell bench press"
    record.category = "strength"
    record.body_part = "chest"
    record.equipment = "barbell"
    record.muscle_group = "chest"
    record.target = "pectorals"
    record.secondary_muscles = ["triceps"]
    record.instructions_en = "Press."
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


class TestPgVectorExerciseRepository:
    @pytest.mark.asyncio
    async def test_orders_by_cosine_distance_and_limits_to_top_k(self) -> None:
        session = _session_returning([_record()])
        repository = PgVectorExerciseRepository(session)

        await repository.search(_vector(), top_k=5)

        statement = session.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": False}))
        assert "ORDER BY" in sql
        # <=> is pgvector's cosine-distance operator.
        assert "<=>" in sql
        assert "LIMIT" in sql
        assert statement._limit == 5

    @pytest.mark.asyncio
    async def test_does_not_filter_by_equipment_when_none_is_given(self) -> None:
        session = _session_returning([_record()])

        await PgVectorExerciseRepository(session).search(_vector(), top_k=3)

        sql = str(session.execute.await_args.args[0])
        assert "equipment IN" not in sql

    @pytest.mark.asyncio
    async def test_prefilters_by_equipment_when_given(self) -> None:
        session = _session_returning([_record()])

        await PgVectorExerciseRepository(session).search(
            _vector(), top_k=3, equipment=["body weight", "dumbbell"]
        )

        sql = str(session.execute.await_args.args[0])
        assert "WHERE" in sql
        assert "equipment IN" in sql

    @pytest.mark.asyncio
    async def test_maps_records_to_domain_exercises(self) -> None:
        session = _session_returning([_record(exercise_id=42)])

        exercises = await PgVectorExerciseRepository(session).search(_vector(), top_k=1)

        assert exercises == [
            Exercise(
                id=42,
                name="barbell bench press",
                category="strength",
                body_part="chest",
                equipment="barbell",
                muscle_group="chest",
                target="pectorals",
                secondary_muscles=["triceps"],
                instructions_en="Press.",
            )
        ]

    @pytest.mark.asyncio
    async def test_tolerates_a_null_secondary_muscles_column(self) -> None:
        session = _session_returning([_record(secondary_muscles=None)])

        exercises = await PgVectorExerciseRepository(session).search(_vector(), top_k=1)

        assert exercises[0].secondary_muscles == []

    @pytest.mark.asyncio
    async def test_refuses_a_query_vector_of_the_wrong_dimension(self) -> None:
        session = _session_returning([])

        with pytest.raises(EmbeddingDimensionError, match="384"):
            await PgVectorExerciseRepository(session).search([0.1, 0.2], top_k=1)

        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_scored_search_preserves_distance_and_stable_ties(self) -> None:
        session = _session_returning([_record()])
        matches = await PgVectorExerciseRepository(session).search_scored(
            _vector(), top_k=8, equipment=["resistance band"], targets=["pectorals"]
        )
        assert matches[0].distance == 0.25
        assert matches[0].similarity == 0.75
        statement = session.execute.await_args.args[0]
        sql = str(statement)
        assert "target IN" in sql
        assert "exercises.id" in sql.split("ORDER BY")[1]
        assert "band" in statement.compile().params["equipment_1"]

    @pytest.mark.asyncio
    async def test_empty_filters_are_not_unrestricted(self) -> None:
        session = _session_returning([])
        await PgVectorExerciseRepository(session).search(_vector(), 8, equipment=[], targets=[])
        sql = str(session.execute.await_args.args[0])
        assert "equipment IN" in sql
        assert "target IN" in sql

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0])
    @pytest.mark.asyncio
    async def test_rejects_nonfinite_or_zero_vector(self, value: float) -> None:
        session = _session_returning([])
        with pytest.raises(ValueError, match="finite and nonzero"):
            await PgVectorExerciseRepository(session).search([value] * 384, 8)
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_normalizes_corpus_equipment_and_group(self) -> None:
        session = _session_returning([
            _record(equipment="band", muscle_group="triceps", target="pectorals")
        ])
        result = await PgVectorExerciseRepository(session).search(_vector(), 8)
        assert result[0].equipment == "resistance band"
        assert result[0].muscle_group == "chest"


class TestExerciseRetriever:
    @pytest.mark.asyncio
    async def test_swap_excluded_equipment_is_a_strict_filter(
        self, profile: InterviewerProfile
    ) -> None:
        profile.training.equipment = ["barbell", "dumbbell"]
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector()]
        repository = AsyncMock(spec=ExerciseRepository)
        source = Exercise(1, "barbell press", target="pectorals", muscle_group="chest")
        candidates = [
            Exercise(
                2,
                "barbell variation",
                equipment="barbell",
                target="pectorals",
                muscle_group="chest",
            ),
            Exercise(
                3, "dumbbell press", equipment="dumbbell", target="pectorals", muscle_group="chest"
            ),
        ]
        repository.search_scored.return_value = [ExerciseMatch(item, 0.2) for item in candidates]
        result = await ExerciseRetriever(embedder, repository).retrieve_alternatives(
            profile, source, "no tengo barra", excluded_equipment=["barbell"]
        )
        assert [item.id for item in result] == [3]
        assert repository.search_scored.await_args.kwargs["equipment"] == [
            "body weight",
            "dumbbell",
        ]
        assert repository.search_scored.await_args.kwargs["target"] == "pectorals"
        assert repository.search_scored.await_args.kwargs["excluded_ids"] == [1]

    @pytest.mark.asyncio
    async def test_swap_without_available_equipment_does_not_search(
        self, profile: InterviewerProfile
    ) -> None:
        profile.training.equipment = ["barbell"]
        embedder = AsyncMock()
        repository = AsyncMock(spec=ExerciseRepository)
        result = await ExerciseRetriever(embedder, repository).retrieve_alternatives(
            profile,
            Exercise(1, "press", target="pectorals"),
            "no gear",
            excluded_equipment=["barbell", "body weight"],
        )
        assert result == []
        repository.search_scored.assert_not_awaited()
        embedder.embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_embeds_one_query_per_muscle_group(self, profile: InterviewerProfile) -> None:
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector() for _ in MUSCLE_GROUPS]
        repository = AsyncMock(spec=ExerciseRepository)
        repository.search_scored.return_value = []

        await ExerciseRetriever(embedder, repository).retrieve(profile)

        queries = embedder.embed.await_args.args[0]
        assert len(queries) == len(MUSCLE_GROUPS)
        assert queries[0].startswith(f"muscle_group: {MUSCLE_GROUPS[0]}")
        assert repository.search_scored.await_count == len(MUSCLE_GROUPS)
        assert repository.search_scored.await_args_list[0].kwargs["targets"] == ("pectorals",)

    @pytest.mark.asyncio
    async def test_deduplicates_exercises_returned_for_several_groups(
        self, profile: InterviewerProfile
    ) -> None:
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector() for _ in MUSCLE_GROUPS]
        repository = AsyncMock(spec=ExerciseRepository)
        # The same exercise comes back for every muscle group.
        repository.search_scored.return_value = [ExerciseMatch(Exercise(id=7, name="burpee"), 0.3)]

        exercises = await ExerciseRetriever(embedder, repository).retrieve(profile)

        assert len(exercises) == 1
        assert exercises[0].id == 7

    @pytest.mark.asyncio
    async def test_passes_top_k_and_equipment_filter_to_the_repository(
        self, profile: InterviewerProfile
    ) -> None:
        home_profile = profile.model_copy(
            update={"training": profile.training.model_copy(update={"environment": "home"})}
        )
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector() for _ in MUSCLE_GROUPS]
        repository = AsyncMock(spec=ExerciseRepository)
        repository.search_scored.return_value = []

        await ExerciseRetriever(embedder, repository, top_k=3).retrieve(home_profile)

        call = repository.search_scored.await_args
        assert call.kwargs["top_k"] == 3
        assert "body weight" in call.kwargs["equipment"]

    @pytest.mark.asyncio
    async def test_propagates_an_embedder_failure(self, profile: InterviewerProfile) -> None:
        embedder = AsyncMock()
        embedder.embed.side_effect = RuntimeError("embedder caido")
        repository = AsyncMock(spec=ExerciseRepository)

        with pytest.raises(RuntimeError):
            await ExerciseRetriever(embedder, repository).retrieve(profile)

        repository.search_scored.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trace_contains_rankings_without_profile_or_vectors(
        self, profile: InterviewerProfile
    ) -> None:
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector()]
        repository = AsyncMock(spec=ExerciseRepository)
        matches = [ExerciseMatch(Exercise(1, "press", target="pectorals"), 0.1)]
        repository.search_scored.return_value = matches
        result = await ExerciseRetriever(
            embedder, repository, muscle_groups=["chest"]
        ).retrieve_traced(profile)
        assert result.groups[0].matches == tuple(matches)
        assert result.groups[0].targets == ("pectorals",)
        assert result.exercises == (matches[0].exercise,)
        assert not hasattr(result, "profile")
        assert not hasattr(result.groups[0], "vector")
