from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fitcoach.api.webhook import webhook
from fitcoach.infrastructure.bot.telegram_bot import to_bot_command
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import (
    get_database_settings,
    get_embedder_settings,
    get_ia_settings,
    get_settings,
    get_vector_database_settings,
)
from fitcoach.infrastructure.database.session import close_database
from fitcoach.infrastructure.observability.telemetry import configure_telemetry, shutdown_telemetry
from fitcoach.infrastructure.vectordb.session import close_vector_database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Fail fast: abort startup on missing/malformed Telegram or IA configuration."""
    configure_logging()
    settings = get_settings()  # ValidationError if token/url/commands are missing
    get_ia_settings()  # ValidationError if any ia_* var is missing/malformed
    for raw in settings.bot_telegram_commands:
        to_bot_command(raw)  # ValueError if a pair is malformed
    get_database_settings()  # ValidationError if the PostgreSQL URL is missing
    get_vector_database_settings()  # ValidationError if the pgVector URL is missing
    get_embedder_settings()  # ValidationError if the embedder URL is missing
    configure_telemetry(app)  # no-op unless otel_exporter_otlp_endpoint is set
    try:
        yield
    finally:
        shutdown_telemetry()
        await close_database()
        await close_vector_database()


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
