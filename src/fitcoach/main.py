import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from telegram import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
from telegram.error import BadRequest, InvalidToken, NetworkError, TelegramError

from fitcoach.api.admin import admin, admin_access
from fitcoach.api.miniapp import miniapp
from fitcoach.api.miniapp_actions import miniapp_actions
from fitcoach.api.webhook import webhook
from fitcoach.domain.constants import Constants
from fitcoach.infrastructure.bot.telegram_bot import get_bot, to_bot_command
from fitcoach.infrastructure.config.logging_config import configure_logging
from fitcoach.infrastructure.config.settings import (
    SchedulerSettings,
    Settings,
    get_database_settings,
    get_embedder_settings,
    get_evaluation_settings,
    get_ia_settings,
    get_scheduler_settings,
    get_settings,
    get_training_settings,
    get_vector_database_settings,
)
from fitcoach.infrastructure.database.session import close_database, get_session_factory
from fitcoach.infrastructure.jobs.scheduler import JobScheduler
from fitcoach.infrastructure.observability.telemetry import configure_telemetry, shutdown_telemetry
from fitcoach.infrastructure.vectordb.session import close_vector_database

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
    get_vector_database_settings()  # ValidationError if the pgVector URL is missing
    get_embedder_settings()  # ValidationError if the embedder URL is missing
    get_training_settings()  # ValidationError if a training_reminder_* var is malformed
    get_evaluation_settings()  # ValidationError if an evaluation_* var is malformed
    scheduler_settings = get_scheduler_settings()  # ValidationError if a scheduler_* var is bad
    configure_telemetry(app)  # no-op unless otel_exporter_otlp_endpoint is set
    await _register_webhook(app, settings)
    scheduler = await _start_scheduler(scheduler_settings)
    try:
        yield
    finally:
        await _stop_scheduler(scheduler)
        shutdown_telemetry()
        await close_database()
        await close_vector_database()


async def _start_scheduler(
    settings: SchedulerSettings,
) -> tuple[asyncio.Event, asyncio.Task[None]] | None:
    if not settings.enabled:
        logger.info("Scheduler is disabled")
        return None
    scheduler = JobScheduler(
        get_session_factory(),
        await get_bot(),
        settings,
        get_training_settings(),
        get_evaluation_settings(),
    )
    stop = asyncio.Event()
    return stop, asyncio.create_task(scheduler.run(stop), name="job-scheduler")


async def _stop_scheduler(scheduler: tuple[asyncio.Event, asyncio.Task[None]] | None) -> None:
    if scheduler is None:
        return
    stop, task = scheduler
    stop.set()
    await task


app = FastAPI(title="FitCoach IA - API de Prueba", lifespan=lifespan)
app.include_router(webhook)
app.include_router(miniapp)
app.include_router(miniapp_actions)
app.include_router(admin)
app.include_router(admin_access)


@app.middleware("http")
async def miniapp_response_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/api/miniapp"):
        response.headers["Cache-Control"] = "no-store"
    if request.url.path.startswith(("/api/miniapp", "/miniapp")):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


_miniapp_directory = Path(__file__).parent / "static" / "miniapp"
if not _miniapp_directory.is_dir():
    _miniapp_directory = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _miniapp_directory.is_dir():
    app.mount("/miniapp", StaticFiles(directory=_miniapp_directory, html=True), name="miniapp")
else:

    @app.get("/miniapp/", include_in_schema=False)
    async def miniapp_not_built() -> None:
        raise HTTPException(status_code=503, detail="Compila primero el frontend de la Mini App.")


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
    try:
        bot = await get_bot()
        logger.info("[webhook 2/4] bot autenticado en Telegram")

        await bot.set_chat_menu_button(
            menu_button=(
                MenuButtonWebApp(
                    text=Constants.TRAINING_NAVIGATION["miniapp"],
                    web_app=WebAppInfo(url=settings.miniapp_url),
                )
                if settings.miniapp_url
                else MenuButtonCommands()
            )
        )

        await bot.set_webhook(
            url=expected_url,
            secret_token=settings.bot_telegram_secret_token.get_secret_value(),
            allowed_updates=["message", "edited_message", "callback_query", "poll_answer"],
            drop_pending_updates=False,
        )
        logger.info("[webhook 3/4] setWebhook aceptado con secreto")

        info = await bot.get_webhook_info()
    except InvalidToken as exc:
        raise RuntimeError("Token invalido: Telegram no reconoce el bot") from exc
    except BadRequest as exc:
        raise RuntimeError(
            f"Telegram rechazo la URL {expected_url!r}: {exc}. Revisar la variable url definida en el entorno"
        ) from exc
    except NetworkError as exc:
        raise RuntimeError(f"no se pudo contactar con la API de Telegram: {exc}") from exc

    except TelegramError as exc:
        raise RuntimeError(f"fallo registrando el webhook: {exc}") from exc

    if info.url != expected_url:
        raise RuntimeError(
            f"webhook mal registrado: Telegram apunta a {info.url!r}, esperado {expected_url!r}"
        )
    logger.info("[webhook 4/4] registro confirmado por Telegram")

    if info.last_error_message:
        logger.warning("Telegram reporta un error de entrega previo")
