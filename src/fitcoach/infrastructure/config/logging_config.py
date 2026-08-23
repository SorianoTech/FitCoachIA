"""Root logging configuration, level driven by the LOG_LEVEL env var."""

import logging
import os
from functools import lru_cache
from types import FrameType

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_APP_ENV = os.getenv("APP_ENV", "dev")
_DEFAULT_LEVEL = "INFO"
_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s.%(qualname)s:%(lineno)d - %(message)s"


class QualnameFormatter(logging.Formatter):
    """Formatter exposing ``%(qualname)s`` as "Class.method" when resolvable.

    ``LogRecord`` carries no class name, only ``funcName``. The caller's frame is
    still on the stack at format time, so ``co_qualname`` (3.11+) recovers it.
    Degrades to ``funcName`` when the frame cannot be matched (e.g. formatting a
    ``LogRecord`` stored earlier by ``caplog``, after the caller's frame is gone).
    """

    def format(self, record: logging.LogRecord) -> str:
        record.qualname = record.funcName
        frame: FrameType | None = logging.currentframe()
        while frame is not None:
            code = frame.f_code
            if code.co_name == record.funcName and code.co_filename == record.pathname:
                record.qualname = code.co_qualname
                break
            frame = frame.f_back
        return super().format(record)


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
    handler.setFormatter(QualnameFormatter(_LOG_FORMAT))
    logging.basicConfig(level=get_logging_settings().level, handlers=[handler])
