"""Settings for rag-doc, read from environment variables prefixed ``RAG_``."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore")

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "rag_doc"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> RagSettings:
    return RagSettings()
