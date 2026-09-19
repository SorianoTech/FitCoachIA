"""Root logging configuration, level driven by the LOG_LEVEL env var."""

import json
import logging
import os
from functools import lru_cache
from types import FrameType
from typing import Any

from opentelemetry import trace
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from fitcoach.infrastructure.observability.telemetry import SERVICE_NAME, SERVICE_VERSION

_APP_ENV = os.getenv("APP_ENV", "dev")
_DEFAULT_LEVEL = "INFO"


def _resolve_qualname(record: logging.LogRecord) -> str:
    """ "Class.method" for the frame that emitted ``record``, falling back to ``funcName``.

    ``LogRecord`` carries no class name, only ``funcName``. The caller's frame is
    still on the stack at format time, so ``co_qualname`` (3.11+) recovers it.
    Degrades to ``funcName`` when the frame cannot be matched (e.g. formatting a
    ``LogRecord`` stored earlier by ``caplog``, after the caller's frame is gone).
    """
    qualname = record.funcName
    frame: FrameType | None = logging.currentframe()
    while frame is not None:
        code = frame.f_code
        if code.co_name == record.funcName and code.co_filename == record.pathname:
            qualname = code.co_qualname
            break
        frame = frame.f_back
    return qualname


class QualnameFormatter(logging.Formatter):
    """Formatter exposing ``%(qualname)s`` as "Class.method" when resolvable."""

    def format(self, record: logging.LogRecord) -> str:
        record.qualname = _resolve_qualname(record)
        return super().format(record)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with trace/span ids for Grafana log<->trace correlation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": f"{record.name}.{_resolve_qualname(record)}",
            "message": record.getMessage(),
            "service.name": SERVICE_NAME,
            "service.version": SERVICE_VERSION,
            "deployment.environment.name": _APP_ENV,
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="log_",
        extra="ignore",
    )

    level: str = _DEFAULT_LEVEL

    @field_validator("level", mode="before")
    @classmethod
    def _normalise_level(cls, value: object) -> object:
        """Accept any case; fall back to INFO instead of failing on a bad value."""
        if isinstance(value, str) and value.strip().upper() in logging.getLevelNamesMapping():
            return value.strip().upper()
        return _DEFAULT_LEVEL


@lru_cache
def get_logging_settings() -> LoggingSettings:
    return LoggingSettings()


def configure_logging() -> None:
    """Install a root handler at the configured level.

    Required because uvicorn's default config declares no root logger, so
    without this every ``fitcoach.*`` record below WARNING is discarded.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=get_logging_settings().level, handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)
