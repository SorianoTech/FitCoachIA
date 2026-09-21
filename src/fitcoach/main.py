import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fitcoach.api.webhook import webhook
from fitcoach.infrastructure.bot.telegram_bot import get_bot, to_bot_command
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import (
    Settings,
    get_database_settings,
    get_ia_settings,
    get_settings,
)
from fitcoach.infrastructure.database.session import close_database
from fitcoach.infrastructure.observability.telemetry import configure_telemetry, shutdown_telemetry

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Fail fast: abort startup on missing/malformed Telegram or IA configuration."""
    configure_logging()
    settings = get_settings()  # ValidationError if token/url/commands are missing
    get_ia_settings()  # ValidationError if any ia_* var is missing/malformed
    for raw in settings.bot_telegram_commands:
        to_bot_command(raw)  # ValueError if a pair is malformed
    get_database_settings()  # ValidationError if the PostgreSQL URL is missing
    configure_telemetry(app)  # no-op unless otel_exporter_otlp_endpoint is set
    await _register_webhook(app, settings)
    try:
        yield
    finally:
        shutdown_telemetry()
        await close_database()


app = FastAPI(title="FitCoach IA - API de Prueba", lifespan=lifespan)
app.include_router(webhook)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "message": "¡FitCoach IA está funcionando!",
        "status": "online",
        "version": "0.1.0",
    }


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy"}


async def _register_webhook(app: FastAPI, settings: Settings) -> None:
    """Registra el webhook con su secreto; aborta el arranque si no se puede."""
    path = app.url_path_for("telegram_webhook")
    expected_url = f"{settings.bot_telegram_webhook_base_url.rstrip('/')}{path}"

    logger.info("[webhook 1/4] resolviendo URL de registro")

    bot = await get_bot()
    logger.info("[webhook 2/4] bot autenticado en Telegram")

    await bot.set_webhook(
        url=expected_url,
        secret_token=settings.bot_telegram_secret_token.get_secret_value(),
        allowed_updates=["message", "edited_message"],
        drop_pending_updates=False,
    )
    logger.info("[webhook 3/4] setWebhook aceptado con secreto")

    info = await bot.get_webhook_info()
    if info.url != expected_url:
        raise RuntimeError(
            f"webhook mal registrado: Telegram apunta a {info.url!r}, esperado {expected_url!r}"
        )
    logger.info("[webhook 4/4] registro confirmado por Telegram")

    if info.last_error_message:
        logger.warning("Telegram reporta un error de entrega previo")
