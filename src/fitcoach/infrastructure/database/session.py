from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fitcoach.infrastructure.config.settings import get_database_settings


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_database_settings().url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def close_database() -> None:
    await get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
