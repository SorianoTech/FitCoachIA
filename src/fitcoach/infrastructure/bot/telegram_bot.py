"""Telegram Bot provider used by the webhook controller."""

from functools import lru_cache

from telegram import Bot, BotCommand

from fitcoach.infrastructure.config.settings import get_settings

_commands_registered = False


def to_bot_command(raw: str) -> BotCommand:
    """Map a ``name:description`` config entry to a Telegram ``BotCommand``."""
    name, separator, description = raw.partition(":")
    if not separator or not name.strip() or not description.strip():
        raise ValueError(f"Invalid Telegram command {raw!r}: expected 'name:description'")
    return BotCommand(name.strip(), description.strip())


@lru_cache
def _create_bot() -> Bot:
    """Build a single shared Bot instance (one HTTP connection pool)."""
    return Bot(base_url=get_settings().bot_telegram_url, token=get_settings().bot_telegram_token)


async def get_bot() -> Bot:
    """FastAPI dependency: a ready-to-use, initialized Telegram Bot.

    ``Bot.initialize()`` is idempotent, so the HTTPX connection pool, the
    one-off ``get_me`` lookup and the command menu registration happen only
    on the first request.
    """
    global _commands_registered
    bot = _create_bot()
    await bot.initialize()
    if not _commands_registered:
        commands = [to_bot_command(raw) for raw in get_settings().bot_telegram_commands]
        await bot.set_my_commands(commands)
        _commands_registered = True
    return bot
