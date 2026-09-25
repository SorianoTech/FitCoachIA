from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from fitcoach.domain.exercise import Exercise
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
    session.scalars = AsyncMock(return_value=scalars)
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

        statement = session.scalars.await_args.args[0]
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

        sql = str(session.scalars.await_args.args[0])
        assert "WHERE" not in sql

    @pytest.mark.asyncio
    async def test_prefilters_by_equipment_when_given(self) -> None:
        session = _session_returning([_record()])

        await PgVectorExerciseRepository(session).search(
            _vector(), top_k=3, equipment=["body weight", "dumbbell"]
        )

        sql = str(session.scalars.await_args.args[0])
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

        session.scalars.assert_not_awaited()


class TestExerciseRetriever:
    @pytest.mark.asyncio
    async def test_embeds_one_query_per_muscle_group(self, profile: InterviewerProfile) -> None:
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector() for _ in MUSCLE_GROUPS]
        repository = AsyncMock(spec=ExerciseRepository)
        repository.search.return_value = []

        await ExerciseRetriever(embedder, repository).retrieve(profile)

        queries = embedder.embed.await_args.args[0]
        assert len(queries) == len(MUSCLE_GROUPS)
        assert queries[0].startswith(f"muscle_group: {MUSCLE_GROUPS[0]}")
        assert repository.search.await_count == len(MUSCLE_GROUPS)

    @pytest.mark.asyncio
    async def test_deduplicates_exercises_returned_for_several_groups(
        self, profile: InterviewerProfile
    ) -> None:
        embedder = AsyncMock()
        embedder.embed.return_value = [_vector() for _ in MUSCLE_GROUPS]
        repository = AsyncMock(spec=ExerciseRepository)
        # The same exercise comes back for every muscle group.
        repository.search.return_value = [Exercise(id=7, name="burpee")]

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
        repository.search.return_value = []

        await ExerciseRetriever(embedder, repository, top_k=3).retrieve(home_profile)

        call = repository.search.await_args
        assert call.kwargs["top_k"] == 3
        assert "body weight" in call.kwargs["equipment"]

    @pytest.mark.asyncio
    async def test_propagates_an_embedder_failure(self, profile: InterviewerProfile) -> None:
        embedder = AsyncMock()
        embedder.embed.side_effect = RuntimeError("embedder caido")
        repository = AsyncMock(spec=ExerciseRepository)

        with pytest.raises(RuntimeError):
            await ExerciseRetriever(embedder, repository).retrieve(profile)

        repository.search.assert_not_awaited()
