from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from fitcoach.infrastructure.bot import telegram_bot
from fitcoach.infrastructure.config.settings import Settings


@pytest.fixture(autouse=True)
def _reset_bot_singleton_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    telegram_bot._create_bot.cache_clear()
    monkeypatch.setattr(telegram_bot, "_commands_registered", False)
    yield
    telegram_bot._create_bot.cache_clear()


@pytest.fixture
def mock_bot_instance() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def patched_bot_class(monkeypatch: pytest.MonkeyPatch, mock_bot_instance: AsyncMock) -> MagicMock:
    bot_cls = MagicMock(return_value=mock_bot_instance)
    monkeypatch.setattr(telegram_bot, "Bot", bot_cls)
    monkeypatch.setattr(
        telegram_bot,
        "get_settings",
        lambda: Settings(
            app_env="test",
            bot_telegram_token="test-token",  # noqa: S106
            bot_telegram_url="http://test-telegram:9999",
        ),
    )
    return bot_cls


class TestGetBot:
    @pytest.mark.asyncio
    async def test_initializes_and_registers_commands_on_first_call(
        self, patched_bot_class: MagicMock, mock_bot_instance: AsyncMock
    ) -> None:
        bot = await telegram_bot.get_bot()

        assert bot is mock_bot_instance
        mock_bot_instance.initialize.assert_awaited_once()
        mock_bot_instance.set_my_commands.assert_awaited_once_with(telegram_bot._BOT_COMMANDS)

    @pytest.mark.asyncio
    async def test_only_registers_commands_once_across_multiple_calls(
        self, patched_bot_class: MagicMock, mock_bot_instance: AsyncMock
    ) -> None:
        await telegram_bot.get_bot()
        await telegram_bot.get_bot()

        assert mock_bot_instance.initialize.await_count == 2
        mock_bot_instance.set_my_commands.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retries_command_registration_after_a_failed_attempt(
        self, patched_bot_class: MagicMock, mock_bot_instance: AsyncMock
    ) -> None:
        mock_bot_instance.set_my_commands.side_effect = [RuntimeError("boom"), None]

        with pytest.raises(RuntimeError):
            await telegram_bot.get_bot()

        await telegram_bot.get_bot()

        assert mock_bot_instance.set_my_commands.await_count == 2
