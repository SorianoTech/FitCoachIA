"""Renew Telegram's short-lived typing action while an operation is running."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from telegram import Bot
from telegram.constants import ChatAction
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def typing_indicator(
    bot: Bot, chat_id: int, thread_id: int | None = None
) -> AsyncIterator[None]:
    async def renew() -> None:
        # Avoid chat actions for fast, deterministic controls.
        await asyncio.sleep(0.3)
        while True:
            try:
                await bot.send_chat_action(
                    chat_id=chat_id, message_thread_id=thread_id, action=ChatAction.TYPING
                )
            except TelegramError:
                logger.warning("Could not send Telegram typing indicator", exc_info=True)
                return
            await asyncio.sleep(4)

    task = asyncio.create_task(renew())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
