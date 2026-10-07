import asyncio
import json
import os
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest

from tests.unit_test.conftest import build_plan_payload


@pytest.mark.asyncio
async def test_legacy_migration_preserves_plan_and_leaves_dates_unknown() -> None:
    base_url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    )
    name = f"training_migration_{uuid4().hex}"
    parsed = urlsplit(base_url)
    url = urlunsplit(parsed._replace(path=f"/{name}"))
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
        await migrate("f3a8c1d4e6b2")
        connection = await asyncpg.connect(url)
        try:
            payload = json.dumps(build_plan_payload())
            plan_id = await connection.fetchval(
                """INSERT INTO training_plans (chat_id, version, plan, report)
                   VALUES (77, 5, $1::json, 'legacy') RETURNING id""",
                payload,
            )
            await connection.execute(
                """INSERT INTO training_sessions (chat_id, status, current_plan_id)
                   VALUES (77, 'active', $1)""",
                plan_id,
            )
        finally:
            await connection.close()
        await migrate("head")
        connection = await asyncpg.connect(url)
        try:
            row = await connection.fetchrow(
                """SELECT p.id, p.version, p.plan, c.started_at, c.expected_end_at,
                          s.current_plan_id
                   FROM training_plans p JOIN training_mesocycles c ON c.id=p.mesocycle_id
                   JOIN training_sessions s ON s.current_plan_id=p.id"""
            )
            assert row["id"] == plan_id
            assert row["version"] == 5
            assert json.loads(row["plan"]) == json.loads(payload)
            assert row["current_plan_id"] == plan_id
            assert row["started_at"] is None
            assert row["expected_end_at"] is None
            assert await connection.fetchval("SELECT count(*) FROM job_execution") == 0
        finally:
            await connection.close()
        await migrate("f3a8c1d4e6b2", "downgrade")
    finally:
        await admin.execute(f'DROP DATABASE "{name}"')
        await admin.close()
