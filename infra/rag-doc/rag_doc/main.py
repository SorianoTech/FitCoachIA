"""rag-doc: public Q&A over the whitelisted docs, by text and voice."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rag_doc.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)8s] %(name)s - %(message)s",
    )
    logger.info("rag-doc starting (qdrant=%s)", settings.qdrant_url)
    yield


app = FastAPI(title="rag-doc", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
