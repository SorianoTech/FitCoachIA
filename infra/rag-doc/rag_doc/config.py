"""Settings for rag-doc, read from environment variables prefixed ``RAG_``."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore")

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "rag_doc"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimensions: int = 384
    corpus_root: str = "/corpus"
    sources_file: str = "/app/sources.yml"
    chunk_max_chars: int = 1200
    log_level: str = "INFO"


@lru_cache
def get_settings() -> RagSettings:
    return RagSettings()
