import json

import asyncpg
import pytest

from tests.it.test_evaluation_migration import Migrate, scratch_database  # noqa: F401
from tests.unit_test.conftest import build_plan_payload

_BEFORE_EVALUATION = "a41bc08d732e"

_INSERT_JOB = """INSERT INTO job_execution (job_type, chat_id, payload, dedup_key, execution_date)
                 VALUES ('evaluation_poll', 77, '{}'::json, $1, now())"""


async def _insert_pending_evaluation(connection: asyncpg.Connection) -> int:
    cycle_id = await connection.fetchval(
        "INSERT INTO training_mesocycles (chat_id) VALUES (77) RETURNING id"
    )
    plan_id = await connection.fetchval(
        """INSERT INTO training_plans (chat_id, version, mesocycle_id, plan, report)
           VALUES (77, 1, $1, $2::json, 'report') RETURNING id""",
        cycle_id,
        json.dumps(build_plan_payload()),
    )
    return await connection.fetchval(
        """INSERT INTO training_evaluation (chat_id, plan_id, mesocycle_id, week_number)
           VALUES (77, $1, $2, 1) RETURNING id""",
        plan_id,
        cycle_id,
    )


@pytest.mark.asyncio
async def test_job_defaults_are_pending_with_a_generated_id(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(_INSERT_JOB, "evaluation_poll:1:1")
        row = await connection.fetchrow("SELECT id, state, attempts FROM job_execution")
    finally:
        await connection.close()
    assert row["id"] is not None
    assert (row["state"], row["attempts"]) == ("pending", 0)


@pytest.mark.asyncio
async def test_rejects_a_duplicated_dedup_key(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(_INSERT_JOB, "evaluation_poll:1:1")
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(_INSERT_JOB, "evaluation_poll:1:1")
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_rejects_an_unknown_job_state(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                """INSERT INTO job_execution
                       (job_type, chat_id, payload, dedup_key, state, execution_date)
                   VALUES ('evaluation_poll', 77, '{}'::json, 'k', 'sending', now())"""
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_rejects_an_unknown_answer_status(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        evaluation_id = await _insert_pending_evaluation(connection)
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                "UPDATE training_evaluation SET answer_status='closed' WHERE id=$1",
                evaluation_id,
            )
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_deleting_a_job_keeps_the_evaluation(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        evaluation_id = await _insert_pending_evaluation(connection)
        job_id = await connection.fetchval(_INSERT_JOB + " RETURNING id", "evaluation_poll:1:1")
        await connection.execute(
            "UPDATE training_evaluation SET job_id=$1 WHERE id=$2", job_id, evaluation_id
        )

        await connection.execute("DELETE FROM job_execution WHERE id=$1", job_id)

        row = await connection.fetchrow(
            "SELECT job_id FROM training_evaluation WHERE id=$1", evaluation_id
        )
    finally:
        await connection.close()
    assert row is not None
    assert row["job_id"] is None


@pytest.mark.asyncio
async def test_downgrade_restores_the_legacy_queue_and_removes_the_job_schema(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")

    await migrate(_BEFORE_EVALUATION, "downgrade")

    connection = await asyncpg.connect(url)
    try:
        jobs = await connection.fetchval("SELECT to_regclass('job_execution')")
        evaluation = await connection.fetchval("SELECT to_regclass('training_evaluation')")
        notifications = await connection.fetchval("SELECT to_regclass('training_notifications')")
    finally:
        await connection.close()
    assert jobs is None
    assert evaluation is None
    assert notifications is not None


@pytest.mark.asyncio
async def test_head_drops_the_legacy_notification_queue(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate("head", "upgrade")
    connection = await asyncpg.connect(url)
    try:
        notifications = await connection.fetchval("SELECT to_regclass('training_notifications')")
    finally:
        await connection.close()
    assert notifications is None
