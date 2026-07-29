"""Application settings loaded from the environment.

Real OS environment variables take precedence over any ``.env`` file, so in
``pre``/``pro``/Docker the values are injected as container env vars and picked
up automatically -- nothing is shipped to production. The ``.env`` files are a
local-development convenience only.

Precedence (high -> low): OS env vars > ``.env.<APP_ENV>`` > ``.env`` > defaults.
"""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_APP_ENV = os.getenv("APP_ENV", "development")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = _APP_ENV
    bot_telegram_token: str
    bot_telegram_url: str  # webhook URL; not needed to send messages


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


@lru_cache
def get_ia_settings() -> IASettings:
    return IASettings()
