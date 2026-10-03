"""Application settings loaded from the environment.

Real OS environment variables take precedence over any ``.env`` file, so in
``pre``/``pro``/Docker the values are injected as container env vars and picked
up automatically -- nothing is shipped to production. The ``.env`` files are a
local-development convenience only.

Precedence (high -> low): OS env vars > ``FITCOACH_ENV_FILE`` when set >
``.env.<APP_ENV>`` > ``.env`` > defaults.
"""

import os
import re
from datetime import timedelta
from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from fitcoach.domain.rate_limiter import UsageLimits

_SECRET_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")

_APP_ENV = os.getenv("APP_ENV", "dev")
_ENV_FILE = os.getenv("FITCOACH_ENV_FILE") or (".env", f".env.{_APP_ENV}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = _APP_ENV
    bot_telegram_url: str  # webhook URL; not needed to send messages
    # "name:description" pairs joined by commas, e.g. "start:Inicia FitCoach,doubts:Resuelve dudas"
    bot_telegram_commands: Annotated[list[str], NoDecode]
    bot_telegram_token: SecretStr
    bot_telegram_secret_token: SecretStr
    bot_telegram_webhook_base_url: str

    @field_validator("bot_telegram_commands", mode="before")
    @classmethod
    def _split_commands(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("bot_telegram_secret_token")
    @classmethod
    def _check_secret_token(cls, value: SecretStr) -> SecretStr:
        if not _SECRET_TOKEN_RE.fullmatch(value.get_secret_value()):
            raise ValueError("bot_telegram_secret_token: 1-256 caracteres de A-Z a-z 0-9 _ -")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


class IASettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="ia_",
        extra="ignore",
    )

    base_url: str
    token: str
    model: str
    temperature: float
    timeout_seconds: int = 60
    # Retries inside the OpenAI client multiply the worst-case latency
    # (timeout x (1 + retries), twice with the JSON repair); past Telegram's
    # webhook timeout the update is re-delivered. Keep it at 0 unless that budget
    # still fits.
    max_retries: int = 0
    max_tokens: int = 0
    history_window_messages: int = 20
    skill: str = "interviewer"

    # --- Trainer (agent 2) ---
    trainer_skill: str = "trainer"
    trainer_timeout: int = 60
    # A full 4-week mesocycle does not fit in the interview's max_tokens.
    trainer_max_tokens: int = 4096
    trainer_history_window_messages: int = 10
    trainer_generation_model: str | None = Field(default=None, min_length=1)
    trainer_consultation_model: str | None = Field(default=None, min_length=1)
    trainer_consultation_max_tokens: int | None = Field(default=None, gt=0)
    trainer_consultation_timeout: float | None = Field(default=None, gt=0)
    trainer_extraction_model: str | None = Field(default=None, min_length=1)
    trainer_extraction_max_tokens: int | None = Field(default=None, gt=0)
    trainer_extraction_timeout: float | None = Field(default=None, gt=0)
    # Exercises retrieved from the vector DB per muscle group.
    rag_top_k: int = 8


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="database_",
        extra="ignore",
    )

    url: str


class VectorDatabaseSettings(BaseSettings):
    """Connection to the read-only pgVector instance holding the exercises corpus.

    Deliberately separate from ``DatabaseSettings``: it is a different server,
    reached with a read-only role, and it never takes part in a business
    transaction.
    """

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="vector_database_",
        extra="ignore",
    )

    url: str


class EmbedderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="embedder_",
        extra="ignore",
    )

    url: str
    timeout_seconds: int = 10


class UsageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="rate_limit_",
        extra="ignore",
    )

    # Punto de corte, no techo: reserva 8.000 bajo el techo real de 158.000.
    token_limit: Annotated[int, Field(gt=0)] = 150_000
    # Deja 51.000 de hueco: lo que cuesta terminar una entrevista. Ver docs/rate-limiter.md.
    soft_ratio: Annotated[float, Field(gt=0, le=1)] = 0.66
    # En minutos, no en horas: dev necesita ventanas cortas para probar el corte.
    window_minutes: Annotated[int, Field(gt=0)] = 1_440

    def to_limits(self) -> UsageLimits:
        return UsageLimits(
            hard_tokens=self.token_limit,
            soft_tokens=int(self.token_limit * self.soft_ratio),
            window=timedelta(minutes=self.window_minutes),
        )


@lru_cache
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()


@lru_cache
def get_vector_database_settings() -> VectorDatabaseSettings:
    return VectorDatabaseSettings()


@lru_cache
def get_embedder_settings() -> EmbedderSettings:
    return EmbedderSettings()


@lru_cache
def get_ia_settings() -> IASettings:
    return IASettings()


@lru_cache
def get_usage_settings() -> UsageSettings:
    return UsageSettings()


class TrainingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", env_prefix="training_", extra="ignore"
    )

    reminders_enabled: bool = False
    reminder_interval_seconds: int = Field(default=300, ge=10)
    reminder_max_attempts: int = Field(default=5, ge=1, le=10)


@lru_cache
def get_training_settings() -> TrainingSettings:
    return TrainingSettings()
