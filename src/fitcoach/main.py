from contextlib import asynccontextmanager

from fastapi import FastAPI

from fitcoach.api.router import main_router
from fitcoach.api.webhook import webhook
from fitcoach.infrastructure.bot.telegram_bot import to_bot_command
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import get_ia_settings, get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Fail fast: abort startup on missing/malformed Telegram or IA configuration."""
    configure_logging()
    settings = get_settings()  # ValidationError if token/url/commands are missing
    get_ia_settings()  # ValidationError if any ia_* var is missing/malformed
    for raw in settings.bot_telegram_commands:
        to_bot_command(raw)  # ValueError if a pair is malformed
    yield


app = FastAPI(title="FitCoach IA - API de Prueba", lifespan=lifespan)
app.include_router(main_router)
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
