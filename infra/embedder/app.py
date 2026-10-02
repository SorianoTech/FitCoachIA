"""Embedding service: turns query text into vectors the exercises corpus understands.

The corpus in ``infra/vector-db`` was vectorized with
``sentence-transformers/all-MiniLM-L6-v2`` (see ``infra/vector-db/loader/loader.py``),
so a query embedded with any other model lands in a different space and cosine
distance stops meaning anything. That is why this lives in its own container:
the model pulls in torch (~2-3 GB) and has no business inside the webhook image.

If ``EMBEDDER_MODEL`` is ever changed, the whole corpus must be re-vectorized
and the SQL dump regenerated.
"""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

logging.basicConfig(
    level=os.getenv("log_level", "INFO").upper(),
    format="%(asctime)s [%(levelname)8s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EXPECTED_DIMENSIONS = int(os.getenv("EMBEDDER_DIMENSIONS", "384"))
MAX_TEXTS = int(os.getenv("EMBEDDER_MAX_TEXTS", "64"))

_model: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the model once, at startup, before /health reports ready."""
    global _model
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", MODEL_NAME)
    _model = SentenceTransformer(MODEL_NAME)
    dimensions = _model.get_sentence_embedding_dimension()
    if dimensions != EXPECTED_DIMENSIONS:
        # Fail loudly here rather than silently returning vectors that cannot be
        # compared against exercises.metadata_vector.
        raise RuntimeError(
            f"Model {MODEL_NAME} produces {dimensions}-dim vectors, "
            f"but the exercises corpus needs {EXPECTED_DIMENSIONS}"
        )
    logger.info("Embedding model ready (%s dimensions)", dimensions)
    yield
    _model = None


app = FastAPI(title="FitCoach IA - Embedder", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class EmbedResponse(BaseModel):
    model: str
    dimensions: int
    vectors: list[list[float]]


@app.get("/health")
async def health() -> dict[str, str]:
    """Ready only once the model is loaded; the compose healthcheck relies on it."""
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model not loaded"
        )
    return {"status": "healthy", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: EmbedRequest) -> EmbedResponse:
    if _model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model not loaded"
        )
    if len(request.texts) > MAX_TEXTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"at most {MAX_TEXTS} texts per request",
        )
    import asyncio

    vectors = (
        await asyncio.to_thread(_model.encode, request.texts, show_progress_bar=False)
    ).tolist()
    return EmbedResponse(model=MODEL_NAME, dimensions=EXPECTED_DIMENSIONS, vectors=vectors)
