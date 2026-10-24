"""rag-doc: public Q&A over the whitelisted docs, by text and voice."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from qdrant_client import QdrantClient

from rag_doc.api import router
from rag_doc.config import get_settings
from rag_doc.embeddings import Embedder
from rag_doc.llm import LLMClient, build_chat_model
from rag_doc.service import AnswerService
from rag_doc.store import VectorStore

logger = logging.getLogger(__name__)


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
    store = VectorStore(QdrantClient(url=settings.qdrant_url), settings.qdrant_collection)
    app.state.answer_service = AnswerService(
        embedder, store, llm, settings.top_k, settings.min_score
    )
    logger.info("rag-doc ready (qdrant=%s, model=%s)", settings.qdrant_url, settings.llm_model)
    yield


app = FastAPI(title="rag-doc", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
