import asyncio
import os
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fitcoach.domain.quota import GLOBAL_SCOPE_ID, QuotaAction, QuotaConfig, QuotaSource
from fitcoach.infrastructure.database.models import (
    InterviewSessionRecord,
    QuotaAuditRecord,
    QuotaConfigRecord,
    TokenUsageRecord,
    TrainingSessionRecord,
)
from fitcoach.infrastructure.database.postgres_quota_repository import PostgresQuotaRepository
from fitcoach.service.quota_service import QuotaService

DEFAULTS = QuotaConfig(token_limit=150_000, soft_ratio=0.66, window_minutes=1_440)
GLOBAL = QuotaConfig(token_limit=1_000, soft_ratio=0.5, window_minutes=60)
USER = QuotaConfig(token_limit=500, soft_ratio=1.0, window_minutes=10)


async def _alembic(url: str, *args: str) -> None:
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["database_url"] = url.replace("postgresql://", "postgresql+asyncpg://")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "alembic",
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, (stdout + stderr).decode()


@pytest_asyncio.fixture
async def database() -> AsyncIterator[str]:
    base_url = os.getenv(
        "IT_DB_URL",
        f"postgresql://fitcoach:fitcoach@localhost:{os.getenv('IT_DB_PORT', '55432')}/fitcoach",
    )
    name = f"quota_{uuid4().hex}"
    url = urlunsplit(urlsplit(base_url)._replace(path=f"/{name}"))
    admin = await asyncpg.connect(base_url)
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        await _alembic(url, "upgrade", "head")
        yield url
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest_asyncio.fixture
async def factory(database: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _usage(chat_id: int, created_at: datetime, tokens: int) -> dict[str, object]:
    return {
        "chat_id": chat_id,
        "agent": "trainer",
        "model": "test",
        "prompt_tokens": tokens,
        "completion_tokens": 0,
        "total_tokens": tokens,
        "latency_ms": 1,
        "status": "success",
        "created_at": created_at,
    }


@pytest.mark.asyncio
async def test_upsert_delete_and_persisted_audit(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        repository = PostgresQuotaRepository(session)
        await repository.save_config(1, GLOBAL_SCOPE_ID, GLOBAL, QuotaAction.SET_GLOBAL)
        await repository.save_config(1, GLOBAL_SCOPE_ID, USER, QuotaAction.SET_GLOBAL)
        await repository.save_config(2, 77, USER, QuotaAction.SET_USER)
        assert await repository.get_configs([GLOBAL_SCOPE_ID, 77, 78]) == {
            GLOBAL_SCOPE_ID: USER,
            77: USER,
        }
        await repository.delete_config(2, 77, QuotaAction.CLEAR_USER)
        assert await repository.get_configs([77]) == {}
        entries = await repository.list_audit(100)
    assert [(e.actor_chat_id, e.subject_chat_id, e.action, e.before, e.after) for e in entries] == [
        (2, 77, QuotaAction.CLEAR_USER, USER, None),
        (2, 77, QuotaAction.SET_USER, None, USER),
        (1, GLOBAL_SCOPE_ID, QuotaAction.SET_GLOBAL, GLOBAL, USER),
        (1, GLOBAL_SCOPE_ID, QuotaAction.SET_GLOBAL, None, GLOBAL),
    ]
    assert all(entry.created_at.utcoffset() == timedelta(0) for entry in entries)
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(QuotaAuditRecord)) == 4


@pytest.mark.asyncio
async def test_concurrent_upserts_last_write_wins_single_row(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def save(limit: int) -> None:
        async with factory() as session:
            config = QuotaConfig(token_limit=limit, soft_ratio=0.5, window_minutes=60)
            await PostgresQuotaRepository(session).save_config(1, 55, config, QuotaAction.SET_USER)

    await asyncio.gather(*(save(limit) for limit in range(100, 110)))
    async with factory() as session:
        rows = list(await session.scalars(select(QuotaConfigRecord)))
        audits = await session.scalar(select(func.count()).select_from(QuotaAuditRecord))
    assert len(rows) == 1
    assert rows[0].token_limit in range(100, 110)
    assert audits == 10


@pytest.mark.asyncio
async def test_database_rejects_out_of_bounds_rows(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                insert(QuotaConfigRecord).values(
                    scope_id=1, token_limit=0, soft_ratio=0.5, window_minutes=1, updated_by=1
                )
            )


@pytest.mark.asyncio
async def test_known_users_are_distinct_ordered_and_paginated(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with factory() as session:
        await session.execute(
            insert(InterviewSessionRecord),
            [{"chat_id": 3, "status": "active"}, {"chat_id": 1, "status": "active"}],
        )
        await session.execute(
            insert(TrainingSessionRecord),
            [{"chat_id": 1, "status": "active"}, {"chat_id": 5, "status": "active"}],
        )
        await session.execute(insert(TokenUsageRecord), [_usage(4, now, 1), _usage(4, now, 1)])
        await session.commit()
        repository = PostgresQuotaRepository(session)
        await repository.save_config(9, GLOBAL_SCOPE_ID, GLOBAL, QuotaAction.SET_GLOBAL)
        await repository.save_config(9, 8, USER, QuotaAction.SET_USER)
        assert await repository.list_known_chat_ids(0, 100) == [1, 3, 4, 5, 8]
        assert await repository.list_known_chat_ids(1, 2) == [3, 4]
        page = await QuotaService(repository, DEFAULTS).list_users(3, 1)
    assert [user.chat_id for user in page.users] == [5]
    assert page.has_more is True


@pytest.mark.asyncio
async def test_consumption_uses_each_users_rolling_window_and_resolution_is_immediate(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    async with factory() as session:
        await session.execute(
            insert(TokenUsageRecord),
            [
                _usage(10, now - timedelta(minutes=60), 100),
                _usage(10, now - timedelta(minutes=60, seconds=1), 1_000),
                _usage(10, now - timedelta(minutes=5), 7),
                _usage(20, now - timedelta(minutes=10), 5),
                _usage(20, now - timedelta(minutes=11), 50),
                _usage(30, now - timedelta(minutes=1), 999),
            ],
        )
        await session.commit()
    async with factory() as admin_session, factory() as webhook_session:
        admin_service = QuotaService(PostgresQuotaRepository(admin_session), DEFAULTS, lambda: now)
        webhook_service = QuotaService(PostgresQuotaRepository(webhook_session), DEFAULTS)
        assert await webhook_service.resolve(20) == DEFAULTS.to_limits()
        await admin_service.set_global(1, GLOBAL)
        await admin_service.set_user(1, 20, USER)
        assert await webhook_service.resolve(20) == USER.to_limits()
        assert await webhook_service.resolve(10) == GLOBAL.to_limits()
        first = await admin_service.user_status(10)
        second = await admin_service.user_status(20)
        unknown = await admin_service.user_status(40)
        await admin_service.clear_user(1, 20)
        assert await webhook_service.resolve(20) == GLOBAL.to_limits()
        await admin_service.clear_global(1)
        assert await webhook_service.resolve(20) == DEFAULTS.to_limits()
    assert (first.used_tokens, first.source) == (107, QuotaSource.GLOBAL)
    assert (second.used_tokens, second.source, second.override) == (5, QuotaSource.USER, USER)
    assert (unknown.used_tokens, unknown.source) == (0, QuotaSource.GLOBAL)
    async with factory() as session:
        remaining = await session.scalar(select(func.count()).select_from(TokenUsageRecord))
    assert remaining == 6


@pytest.mark.asyncio
async def test_migration_downgrades_cleanly(database: str) -> None:
    await _alembic(database, "downgrade", "b82ac09d743f")
    connection = await asyncpg.connect(database)
    try:
        tables = await connection.fetchval(
            "SELECT count(*) FROM pg_tables WHERE tablename IN ('quota_configs', 'quota_audit')"
        )
    finally:
        await connection.close()
    assert tables == 0
    await _alembic(database, "upgrade", "head")
