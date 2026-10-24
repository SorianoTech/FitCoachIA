"""rag-doc: public Q&A over the whitelisted docs, by text and voice."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import openai
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from qdrant_client import QdrantClient

from rag_doc.api import router
from rag_doc.config import RagSettings, get_settings
from rag_doc.embeddings import Embedder
from rag_doc.limits import RateLimiter
from rag_doc.llm import LLMClient, build_chat_model
from rag_doc.service import AnswerService
from rag_doc.store import VectorStore
from rag_doc.texts import MAX_AUDIO_SECONDS
from rag_doc.voice import (
    CloudTranscriber,
    FallbackTranscriber,
    PiperSynthesizer,
    SpeechToText,
    WhisperTranscriber,
)

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


def build_stt(settings: RagSettings) -> SpeechToText:
    local = WhisperTranscriber(settings.stt_model, settings.stt_model_dir, MAX_AUDIO_SECONDS)
    if settings.stt_provider != "cloud":
        return local
    key = settings.stt_cloud_api_key or settings.llm_api_key
    client = openai.OpenAI(
        api_key=key.get_secret_value() if key else "",
        base_url=settings.stt_cloud_base_url,
        timeout=settings.stt_cloud_timeout_seconds,
        max_retries=1,
    )
    return FallbackTranscriber(CloudTranscriber(client, settings.stt_cloud_model), local)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)8s] %(name)s - %(message)s",
    )
    # Fail fast: without a key every question would end in a provider error
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value():
        raise RuntimeError("RAG_LLM_API_KEY is required")
    embedder = Embedder(settings.embedding_model, settings.embedding_dimensions)
    embedder.embed_query("warm-up")
    llm = LLMClient(build_chat_model(settings))
    app.state.stt = build_stt(settings)
    app.state.tts = PiperSynthesizer(settings.tts_voice_path)
    store = VectorStore(QdrantClient(url=settings.qdrant_url), settings.qdrant_collection)
    app.state.answer_service = AnswerService(
        embedder, store, llm, settings.top_k, settings.min_score
    )
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute, settings.daily_call_cap)
    logger.info("rag-doc ready (qdrant=%s, model=%s)", settings.qdrant_url, settings.llm_model)
    yield


app = FastAPI(title="rag-doc", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# Mounted last so /health and /api/* take precedence
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
