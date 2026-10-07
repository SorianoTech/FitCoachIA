import asyncpg
import pytest

from tests.it.test_evaluation_migration import (  # noqa: F401
    Migrate,
    _insert_current_cycle,
    scratch_database,
)

_DEPLOYED_HEAD = "c7a9e2d4f6b1"

_SET_END = (
    "UPDATE training_mesocycles SET expected_end_at = now() + $2::text::interval WHERE id = $1"
)
_INSERT_NOTIFICATION = """INSERT INTO training_notifications (mesocycle_id, occasion, state, due_at, attempts)
                          VALUES ($1, $2, $3, now() - interval '1 hour', $4)"""


async def _jobs(connection: asyncpg.Connection, job_type: str) -> list[asyncpg.Record]:
    return await connection.fetch(
        """SELECT dedup_key, state, attempts, chat_id, payload->>'mesocycle_id' AS cycle,
                  executed_at IS NOT NULL AS finished, execution_date <= now() AS overdue
           FROM job_execution WHERE job_type=$1 ORDER BY dedup_key""",
        job_type,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("legacy_state", "expected_state"),
    [
        ("pending", "pending"),
        ("sending", "pending"),
        ("sent", "done"),
        ("failed", "failed"),
        ("cancelled", "cancelled"),
    ],
)
async def test_legacy_notification_state_maps_to_a_job_state(
    scratch_database: tuple[str, Migrate],  # noqa: F811
    legacy_state: str,
    expected_state: str,
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="3 days")
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 0, legacy_state, 2)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert [(r["dedup_key"], r["state"], r["attempts"]) for r in reminders] == [
        (f"training_reminder:{cycle_id}:0", expected_state, 2)
    ]
    assert reminders[0]["finished"] == (expected_state in ("done", "failed"))


@pytest.mark.asyncio
async def test_pending_notification_of_a_closed_cycle_is_cancelled(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(
            connection, chat_id=77, started="10 days", completed=True
        )
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 0, "pending", 0)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        states = [r["state"] for r in await _jobs(connection, "training_reminder")]
    finally:
        await connection.close()
    assert states == ["cancelled"]


@pytest.mark.asyncio
async def test_dated_cycle_without_notifications_gets_its_reminder_at_expected_end(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="3 days")
        await connection.execute(_SET_END, cycle_id, "-1 hour")
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert [(r["dedup_key"], r["state"], r["overdue"]) for r in reminders] == [
        (f"training_reminder:{cycle_id}:0", "pending", True)
    ]


@pytest.mark.asyncio
async def test_does_not_register_a_second_reminder_when_one_was_already_sent(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="30 days")
        await connection.execute(_SET_END, cycle_id, "-2 days")
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 0, "sent", 1)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        states = [r["state"] for r in await _jobs(connection, "training_reminder")]
    finally:
        await connection.close()
    assert states == ["done"]


@pytest.mark.asyncio
async def test_postponed_cycle_keeps_its_pending_reminder_and_adds_no_duplicate(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="30 days")
        await connection.execute(_SET_END, cycle_id, "2 days")
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 0, "cancelled", 0)
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 1, "pending", 0)
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert [(r["dedup_key"], r["state"]) for r in reminders] == [
        (f"training_reminder:{cycle_id}:0", "cancelled"),
        (f"training_reminder:{cycle_id}:1", "pending"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("end", [None, "past-closed"], ids=["undated", "closed"])
async def test_does_not_register_a_reminder_for_cycles_that_cannot_remind(
    scratch_database: tuple[str, Migrate],  # noqa: F811
    end: str | None,
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(
            connection, chat_id=77, started=None if end is None else "30 days", completed=bool(end)
        )
        if end:
            await connection.execute(_SET_END, cycle_id, "-2 days")
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert reminders == []


@pytest.mark.asyncio
async def test_cycle_with_reminders_off_gets_no_reminder(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="3 days")
        await connection.execute(_SET_END, cycle_id, "-1 hour")
        await connection.execute(
            "UPDATE training_mesocycles SET reminders_enabled=false WHERE id=$1", cycle_id
        )
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert reminders == []


@pytest.mark.asyncio
async def test_registers_future_polls_and_reminder_with_their_dedup_keys(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="10 days")
        await connection.execute(_SET_END, cycle_id, "18 days")
    finally:
        await connection.close()

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        polls = await _jobs(connection, "evaluation_poll")
        reminders = await _jobs(connection, "training_reminder")
    finally:
        await connection.close()
    assert [(r["dedup_key"], r["chat_id"]) for r in polls] == [
        (f"evaluation_poll:{cycle_id}:{week}", 77) for week in (2, 3, 4)
    ]
    assert len(reminders) == 1


@pytest.mark.asyncio
async def test_empty_database_migrates_without_jobs(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")

    await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        count = await connection.fetchval("SELECT count(*) FROM job_execution")
    finally:
        await connection.close()
    assert count == 0


@pytest.mark.asyncio
async def test_failed_migration_is_rolled_back_entirely_and_leaves_the_version_untouched(
    scratch_database: tuple[str, Migrate],  # noqa: F811
) -> None:
    url, migrate = scratch_database
    await migrate(_DEPLOYED_HEAD, "upgrade")
    connection = await asyncpg.connect(url)
    try:
        cycle_id = await _insert_current_cycle(connection, chat_id=77, started="3 days")
        # A goal longer than the new varchar(32) column makes the backfill revision fail.
        await connection.execute(
            "UPDATE training_plans SET plan = jsonb_set(plan::jsonb, '{goal}', to_jsonb($1::text))::json",
            "x" * 40,
        )
        await connection.execute(_INSERT_NOTIFICATION, cycle_id, 0, "pending", 0)
    finally:
        await connection.close()

    with pytest.raises(AssertionError):
        await migrate("head", "upgrade")

    connection = await asyncpg.connect(url)
    try:
        version = await connection.fetchval("SELECT version_num FROM alembic_version")
        jobs = await connection.fetchval("SELECT to_regclass('job_execution')")
        notifications = await connection.fetchval("SELECT count(*) FROM training_notifications")
        goal = await connection.fetchval(
            """SELECT count(*) FROM information_schema.columns
               WHERE table_name='training_plans' AND column_name='goal'"""
        )
    finally:
        await connection.close()
    assert version == _DEPLOYED_HEAD
    assert jobs is None
    assert goal == 0
    assert notifications == 1
