"""Application settings loaded from the environment.

Real OS environment variables take precedence over any ``.env`` file, so in
``pre``/``pro``/Docker the values are injected as container env vars and picked
up automatically -- nothing is shipped to production. The ``.env`` files are a
local-development convenience only.

Precedence (high -> low): OS env vars > ``.env.<APP_ENV>`` > ``.env`` > defaults.
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
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
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="ia_",
        extra="ignore",
    )

    base_url: str
    token: str
    model: str
    temperature: float
    timeout_seconds: int = 0
    max_tokens: int = 0
    history_window_messages: int = 20
    skill: str = "interviewer"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="database_",
        extra="ignore",
    )

    url: str


class UsageSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
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
def get_ia_settings() -> IASettings:
    return IASettings()


@lru_cache
def get_usage_settings() -> UsageSettings:
    return UsageSettings()
