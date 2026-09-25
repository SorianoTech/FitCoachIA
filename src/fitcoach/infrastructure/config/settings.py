"""Application settings loaded from the environment.

Real OS environment variables take precedence over any ``.env`` file, so in
``pre``/``pro``/Docker the values are injected as container env vars and picked
up automatically -- nothing is shipped to production. The ``.env`` files are a
local-development convenience only.

Precedence (high -> low): OS env vars > ``.env.<APP_ENV>`` > ``.env`` > defaults.
"""

import os
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_APP_ENV = os.getenv("APP_ENV", "dev")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = _APP_ENV
    bot_telegram_token: str
    bot_telegram_url: str  # webhook URL; not needed to send messages
    # "name:description" pairs joined by commas, e.g. "start:Inicia FitCoach,doubts:Resuelve dudas"
    bot_telegram_commands: Annotated[list[str], NoDecode]

    @field_validator("bot_telegram_commands", mode="before")
    @classmethod
    def _split_commands(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
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

    # --- Trainer (agent 2) ---
    trainer_skill: str = "trainer"
    # A full 4-week mesocycle does not fit in the interview's max_tokens.
    trainer_max_tokens: int = 4096
    trainer_history_window_messages: int = 10
    # Exercises retrieved from the vector DB per muscle group.
    rag_top_k: int = 8


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
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
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="vector_database_",
        extra="ignore",
    )

    url: str


class EmbedderSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", f".env.{_APP_ENV}"),
        env_file_encoding="utf-8",
        env_prefix="embedder_",
        extra="ignore",
    )

    url: str
    timeout_seconds: int = 10


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
