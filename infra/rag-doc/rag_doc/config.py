"""Settings for rag-doc, read from environment variables prefixed ``RAG_``."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class RagSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", extra="ignore")

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "rag_doc"
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dimensions: int = 768
    corpus_root: str = "/corpus"
    sources_file: str = "/app/sources.yml"
    chunk_max_chars: int = 1200
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "meta-llama/llama-3.3-70b-instruct"
    llm_timeout_seconds: float = 30.0
    llm_max_tokens: int = 600
    llm_max_retries: int = 2
    llm_reasoning_effort: str = "default"
    top_k: int = 5
    min_score: float = 0.0
    rate_limit_per_minute: int = 10
    stt_provider: str = "cloud"
    stt_cloud_base_url: str = "https://api.openai.com/v1"
    stt_cloud_api_key: SecretStr | None = None
    stt_cloud_model: str = "gpt-4o-mini-transcribe"
    stt_cloud_timeout_seconds: float = 20.0
    stt_model: str = "small"
    stt_model_dir: str = "/opt/whisper"
    tts_voice_path: str = "/opt/piper/es_ES-davefx-medium.onnx"
    daily_call_cap: int = 500
    trust_proxy_headers: bool = True
    log_level: str = "INFO"


@lru_cache
def get_settings() -> RagSettings:
    return RagSettings()
