import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from tests.unit_test.conftest import build_plan_payload

_BEFORE_EVALUATION = "a41bc08d732e"

Migrate = Callable[[str, str], Awaitable[None]]


@pytest_asyncio.fixture
async def scratch_database() -> AsyncIterator[tuple[str, Migrate]]:
    base_url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    )
    name = f"evaluation_migration_{uuid4().hex}"
    url = urlunsplit(urlsplit(base_url)._replace(path=f"/{name}"))
    admin = await asyncpg.connect(base_url)
    await admin.execute(f'CREATE DATABASE "{name}"')

    async def migrate(target: str, direction: str = "upgrade") -> None:
        env = dict(os.environ)
        env.pop("DATABASE_URL", None)
        env["database_url"] = url.replace("postgresql://", "postgresql+asyncpg://")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            direction,
            target,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        assert process.returncode == 0, (stdout + stderr).decode()

    try:
        yield url, migrate
    finally:
        await admin.execute(f'DROP DATABASE "{name}"')
        await admin.close()


async def _insert_plan(connection: asyncpg.Connection, chat_id: int) -> tuple[int, int]:
    cycle_id = await connection.fetchval(
        "INSERT INTO training_mesocycles (chat_id) VALUES ($1) RETURNING id", chat_id
    )
    plan_id = await connection.fetchval(
        """INSERT INTO training_plans (chat_id, version, mesocycle_id, plan, report)
           VALUES ($1, 1, $2, $3::json, 'report') RETURNING id""",
        chat_id,
        cycle_id,
        json.dumps(build_plan_payload()),
    )
    return plan_id, cycle_id


async def _insert_current_cycle(
    connection: asyncpg.Connection,
    chat_id: int,
    started: str | None,
    completed: bool = False,
) -> int:
    """Cycle pointed at by the chat session; ``started`` is a SQL interval before now()."""
    cycle_id: int = await connection.fetchval(
        """INSERT INTO training_mesocycles (chat_id, started_at, completed_at)
           VALUES ($1,
                   CASE WHEN $2::text IS NULL THEN NULL ELSE now() - $2::interval END,
                   CASE WHEN $3 THEN now() END)
           RETURNING id""",
        chat_id,
        started,
        completed,
    )
    plan_id = await connection.fetchval(
        """INSERT INTO training_plans (chat_id, version, mesocycle_id, plan, report)
           VALUES ($1, 1, $2, $3::json, 'report') RETURNING id""",
        chat_id,
        cycle_id,
        json.dumps(build_plan_payload()),
    )
    await connection.execute(
        """INSERT INTO training_sessions (chat_id, status, current_plan_id)
           VALUES ($1, 'active', $2)""",
        chat_id,
        plan_id,
    )
    return cycle_id


async def _scheduled_weeks(connection: asyncpg.Connection, chat_id: int) -> list[int]:
    rows = await connection.fetch(
        """SELECT week_number FROM training_evaluation
           WHERE chat_id=$1 AND state='pending' ORDER BY week_number""",
        chat_id,
    )
    return [row["week_number"] for row in rows]


async def _insert_evaluation(
    connection: asyncpg.Connection, plan_id: int, cycle_id: int, week: int, score: int | None
) -> None:
    await connection.execute(
        """INSERT INTO training_evaluation
               (chat_id, plan_id, mesocycle_id, goal, week_number, due_at, score)
           VALUES (77, $1, $2, 'gain_muscle', $3, now(), $4)""",
        plan_id,
        cycle_id,
        week,
        score,
    )


@pytest.mark.asyncio
async def test_backfills_the_goal_of_existing_plans(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate(_BEFORE_EVALUATION, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        plan_id, _ = await _insert_plan(connection, chat_id=77)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        goal = await connection.fetchval("SELECT goal FROM training_plans WHERE id=$1", plan_id)
    finally:
        await connection.close()
    assert goal == "gain_muscle"


@pytest.mark.asyncio
async def test_schedules_only_the_future_weeks_of_open_cycles(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate(_BEFORE_EVALUATION, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        await _insert_current_cycle(connection, chat_id=77, started="10 days")
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        weeks = await _scheduled_weeks(connection, chat_id=77)
        overdue = await connection.fetchval(
            "SELECT count(*) FROM training_evaluation WHERE due_at <= now()"
        )
    finally:
        await connection.close()
    assert weeks == [2, 3, 4]
    assert overdue == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("started", "completed"),
    [("10 days", True), (None, False), ("40 days", False)],
    ids=["closed", "undated", "all-weeks-past"],
)
async def test_does_not_schedule_cycles_without_future_weeks(
    scratch_database: tuple[str, Migrate], started: str | None, completed: bool
) -> None:
    url, migrate = scratch_database
    await migrate(_BEFORE_EVALUATION, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        await _insert_current_cycle(connection, chat_id=77, started=started, completed=completed)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        weeks = await _scheduled_weeks(connection, chat_id=77)
    finally:
        await connection.close()
    assert weeks == []


@pytest.mark.asyncio
async def test_does_not_schedule_a_cycle_that_is_no_longer_current(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate(_BEFORE_EVALUATION, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        # Open and dated, but no session points at its plan.
        await connection.execute(
            """INSERT INTO training_mesocycles (chat_id, started_at)
               VALUES (77, now() - interval '3 days')"""
        )
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        weeks = await _scheduled_weeks(connection, chat_id=77)
    finally:
        await connection.close()
    assert weeks == []


@pytest.mark.asyncio
async def test_evaluation_survives_the_deletion_of_its_plan_and_cycle(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        plan_id, cycle_id = await _insert_plan(connection, chat_id=77)
        await _insert_evaluation(connection, plan_id, cycle_id, week=1, score=4)

        # Same order as the /interview reset: plans first, then cycles.
        await connection.execute("DELETE FROM training_plans WHERE id=$1", plan_id)
        await connection.execute("DELETE FROM training_mesocycles WHERE id=$1", cycle_id)

        row = await connection.fetchrow(
            "SELECT plan_id, mesocycle_id, score, goal FROM training_evaluation"
        )
    finally:
        await connection.close()
    assert row["plan_id"] is None
    assert row["mesocycle_id"] is None
    assert row["score"] == 4
    assert row["goal"] == "gain_muscle"


@pytest.mark.asyncio
@pytest.mark.parametrize("score", [-1, 6])
async def test_rejects_a_score_outside_zero_to_five(
    scratch_database: tuple[str, Migrate], score: int
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        plan_id, cycle_id = await _insert_plan(connection, chat_id=77)
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_evaluation(connection, plan_id, cycle_id, week=1, score=score)
    finally:
        await connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("week", [0, 5])
async def test_rejects_a_week_outside_the_mesocycle(
    scratch_database: tuple[str, Migrate], week: int
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        plan_id, cycle_id = await _insert_plan(connection, chat_id=77)
        with pytest.raises(asyncpg.CheckViolationError):
            await _insert_evaluation(connection, plan_id, cycle_id, week=week, score=None)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_rejects_two_evaluations_for_the_same_cycle_week(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        plan_id, cycle_id = await _insert_plan(connection, chat_id=77)
        await _insert_evaluation(connection, plan_id, cycle_id, week=2, score=None)
        with pytest.raises(asyncpg.UniqueViolationError):
            await _insert_evaluation(connection, plan_id, cycle_id, week=2, score=None)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_downgrade_removes_the_evaluation_schema(
    scratch_database: tuple[str, Migrate],
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")

    await migrate(_BEFORE_EVALUATION, "downgrade")

    connection = await asyncpg.connect(url)
    try:
        table = await connection.fetchval("SELECT to_regclass('training_evaluation')")
        goal_column = await connection.fetchval(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name='training_plans' AND column_name='goal'"""
        )
    finally:
        await connection.close()
    assert table is None
    assert goal_column == 0
