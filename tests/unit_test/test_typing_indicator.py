import asyncio
from unittest.mock import AsyncMock

import pytest
from telegram import Bot
from telegram.error import NetworkError

from fitcoach.service.typing_indicator import typing_indicator


@pytest.mark.asyncio
async def test_fast_operation_does_not_emit_typing() -> None:
    bot = AsyncMock(spec=Bot)
    async with typing_indicator(bot, 7, 42):
        await asyncio.sleep(0)
    bot.send_chat_action.assert_not_awaited()


@pytest.mark.asyncio
async def test_typing_renews_preserves_thread_and_stops_on_exit() -> None:
    bot = AsyncMock(spec=Bot)
    async with typing_indicator(bot, 7, 42):
        await asyncio.sleep(4.4)
    assert bot.send_chat_action.await_count == 2
    bot.send_chat_action.assert_awaited_with(chat_id=7, message_thread_id=42, action="typing")
    await asyncio.sleep(0.1)
    assert bot.send_chat_action.await_count == 2


@pytest.mark.asyncio
async def test_transport_failure_logs_without_interrupting_work(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bot = AsyncMock(spec=Bot)
    bot.send_chat_action.side_effect = NetworkError("unavailable")
    async with typing_indicator(bot, 7):
        await asyncio.sleep(0.4)
    assert "Could not send Telegram typing indicator" in caplog.text
    assert bot.send_chat_action.await_count == 1


@pytest.mark.asyncio
async def test_operation_error_is_preserved_and_indicator_cancelled() -> None:
    bot = AsyncMock(spec=Bot)

    async def operation() -> None:
        async with typing_indicator(bot, 7):
            await asyncio.sleep(0.4)
            raise ValueError("operation failed")

    with pytest.raises(ValueError, match="operation failed"):
        await operation()
    assert bot.send_chat_action.await_count == 1


@pytest.mark.asyncio
async def test_cancellation_cleans_up_chat_action_task() -> None:
    bot = AsyncMock(spec=Bot)
    entered = asyncio.Event()

    async def operation() -> None:
        async with typing_indicator(bot, 7):
            entered.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(operation())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.4)
    bot.send_chat_action.assert_not_awaited()
