"""Engine and session factory for the read-only pgVector instance.

Kept completely apart from ``infrastructure/database/session.py``: different
server, different credentials, and no shared transaction. A retrieval failure
must never be able to roll back a conversation turn.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fitcoach.infrastructure.config.settings import get_vector_database_settings


@lru_cache
def get_vector_engine() -> AsyncEngine:
    return create_async_engine(get_vector_database_settings().url, pool_pre_ping=True)


@lru_cache
def get_vector_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_vector_engine(), expire_on_commit=False)


async def get_vector_session() -> AsyncIterator[AsyncSession]:
    async with get_vector_session_factory()() as session:
        yield session


@lru_cache
def get_vector_writer_engine() -> AsyncEngine | None:
    writer_url = get_vector_database_settings().writer_url
    return create_async_engine(writer_url, pool_pre_ping=True) if writer_url else None


@lru_cache
def get_vector_writer_session_factory() -> async_sessionmaker[AsyncSession] | None:
    engine = get_vector_writer_engine()
    return async_sessionmaker(engine, expire_on_commit=False) if engine is not None else None


async def get_vector_writer_session() -> AsyncIterator[AsyncSession | None]:
    factory = get_vector_writer_session_factory()
    if factory is None:
        yield None
        return
    async with factory() as session:
        yield session


async def close_vector_database() -> None:
    if get_vector_engine.cache_info().currsize:
        await get_vector_engine().dispose()
    get_vector_session_factory.cache_clear()
    get_vector_engine.cache_clear()
    if get_vector_writer_engine.cache_info().currsize:
        writer_engine = get_vector_writer_engine()
        if writer_engine is not None:
            await writer_engine.dispose()
    get_vector_writer_session_factory.cache_clear()
    get_vector_writer_engine.cache_clear()
