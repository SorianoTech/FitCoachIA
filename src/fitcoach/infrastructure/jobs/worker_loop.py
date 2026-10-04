"""Periodic loop shared by the scheduled Telegram workers."""

import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from fitcoach.infrastructure.bot.telegram_bot import get_bot
from fitcoach.infrastructure.database.session import close_database, get_session_factory

logger = logging.getLogger(__name__)

Batch = Callable[[AsyncSession, Bot], Awaitable[int]]


async def run_periodically(name: str, batch: Batch, interval_seconds: int, once: bool) -> None:
    """One DB session per tick until SIGTERM; ``once`` runs a single bounded batch."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    bot = await get_bot()
    try:
        while not stop.is_set():
            try:
                async with get_session_factory()() as session:
                    await batch(session, bot)
            except SQLAlchemyError:
                logger.exception("%s database/schema unavailable", name)
                if once:
                    raise
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except TimeoutError:
                continue
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
        await bot.shutdown()
        await close_database()
