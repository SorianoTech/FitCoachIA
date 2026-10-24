"""Real pgvector ranking with synthetic rows rolled back after each test."""

import os
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from fitcoach.domain.interviewer_profile import InterviewerProfile
from fitcoach.infrastructure.vectordb.models import ExerciseRecord
from fitcoach.infrastructure.vectordb.pgvector_exercise_repository import PgVectorExerciseRepository
from fitcoach.service.agent.exercise_retriever import ExerciseRetriever


def _axis(index: int = 0, sign: float = 1.0) -> list[float]:
    vector = [0.0] * 384
    vector[index] = sign
    return vector


@pytest_asyncio.fixture
async def vector_session() -> AsyncIterator[AsyncSession]:
    url = make_url(
        os.getenv(
            "IT_VECTOR_DB_URL",
            f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_VECTOR_DB_PORT', '55433')}/fitcoach",
        )
    ).set(drivername="postgresql+asyncpg")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            async with AsyncSession(bind=connection) as session:
                session.add_all([
                    ExerciseRecord(
                        id=99001 + offset,
                        name=f"synthetic scored exercise {offset}",
                        equipment=equipment,
                        muscle_group=group,
                        target=target,
                        metadata_vector=vector,
                    )
                    for offset, (equipment, group, target, vector) in enumerate([
                        ("band", "triceps", "pectorals", _axis()),
                        ("resistance band", "shoulders", "pectorals", _axis(1)),
                        ("band", "core", "pectorals", _axis(sign=-1)),
                        ("dumbbell", "chest", "pectorals", _axis()),
                        ("band", "back", "lats", _axis()),
                        ("band", "deltoids", "pectorals", _axis()),
                    ])
                ])
                await session.flush()
                try:
                    yield session
                finally:
                    await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cosine_scores_filters_aliases_and_empty_constraints(
    vector_session: AsyncSession,
) -> None:
    repository = PgVectorExerciseRepository(vector_session)
    matches = await repository.search_scored(
        _axis(), 8, equipment=["resistance band"], targets=["pectorals"]
    )
    assert [match.exercise.id for match in matches] == [99001, 99006, 99002, 99003]
    assert [match.distance for match in matches] == pytest.approx([0, 0, 1, 2], abs=1e-6)
    assert [match.similarity for match in matches] == pytest.approx([1, 1, 0, -1], abs=1e-6)
    assert {match.exercise.muscle_group for match in matches} == {"chest"}
    assert {match.exercise.equipment for match in matches} == {"resistance band"}
    assert await repository.search(_axis(), 8, equipment=[]) == []
    assert await repository.search(_axis(), 8, targets=[]) == []
    excluded = await repository.search(
        _axis(), 8, equipment=["resistance band"], target="pectorals", excluded_ids=[99001]
    )
    assert [item.id for item in excluded] == [99006, 99002, 99003]


@pytest.mark.asyncio
async def test_retrieval_and_swap_ignore_misleading_raw_group(
    vector_session: AsyncSession,
) -> None:
    profile = InterviewerProfile.model_validate_json(
        Path("evals/trainer/cases/short_sessions_outdoors_2d/profile.json").read_text()
    )
    profile.training.equipment = ["bandas"]
    embedder = AsyncMock()
    embedder.embed.return_value = [_axis()]
    retriever = ExerciseRetriever(
        embedder, PgVectorExerciseRepository(vector_session), muscle_groups=["chest"]
    )
    trace = await retriever.retrieve_traced(profile)
    assert {item.id for item in trace.exercises} >= {99001, 99002, 99003}
    assert 99004 not in {item.id for item in trace.exercises}
    assert 99005 not in {item.id for item in trace.exercises}
    source = next(item for item in trace.exercises if item.id == 99001)
    alternatives = await retriever.retrieve_alternatives(profile, source, "preferencia")
    assert {item.id for item in alternatives} >= {99002, 99003}
    assert source.id not in {item.id for item in alternatives}
    assert all(item.target == "pectorals" for item in alternatives)
    assert (
        await retriever.retrieve_alternatives(
            profile, source, "sin bandas", excluded_equipment=["band", "body weight"]
        )
        == []
    )
