"""HTTP client for the embedding service.

Failures are mapped onto the shared ``AgentError`` taxonomy so the service layer
handles a dead embedder exactly like a dead model provider: one safe message to
the user, never a stack trace or an upstream body.
"""

import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

import httpx

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.infrastructure.config.settings import EmbedderSettings, get_embedder_settings
from fitcoach.infrastructure.vectordb.models import EMBEDDING_DIMENSIONS

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbedderClient:
    def __init__(self, base_url: str, timeout_seconds: int = 10) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(f"{self._base_url}/embed", json={"texts": list(texts)})
                response.raise_for_status()
                payload = response.json()
        except httpx.TimeoutException as exc:
            logger.warning("Embedder timed out after %ss", self._timeout_seconds)
            raise AgentError(AgentErrorCode.TIMEOUT, retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            logger.warning("Embedder returned HTTP %s", exc.response.status_code)
            raise self._error_for_status(exc.response.status_code) from exc
        except httpx.HTTPError as exc:
            logger.warning("Embedder is unreachable: %s", type(exc).__name__)
            raise AgentError(AgentErrorCode.UNAVAILABLE, retryable=True) from exc

        vectors = payload.get("vectors") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            logger.error("Embedder returned an unusable payload")
            raise AgentError(AgentErrorCode.INVALID_OUTPUT, retryable=True)
        for vector in vectors:
            # A wrong dimension means the service is running a different model
            # than the one the corpus was built with: cosine distance would be
            # meaningless, so refuse instead of returning bad matches.
            if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
                logger.error(
                    "Embedder returned %s dimensions, expected %s",
                    len(vector) if isinstance(vector, list) else "non-list",
                    EMBEDDING_DIMENSIONS,
                )
                raise AgentError(AgentErrorCode.INVALID_OUTPUT, retryable=False)
        return vectors

    @staticmethod
    def _error_for_status(status_code: int) -> AgentError:
        if status_code == 408:
            return AgentError(AgentErrorCode.TIMEOUT, retryable=True)
        if status_code == 429:
            return AgentError(AgentErrorCode.RATE_LIMITED, retryable=True)
        if status_code in {400, 422}:
            return AgentError(AgentErrorCode.INVALID_REQUEST, retryable=False)
        return AgentError(AgentErrorCode.UNAVAILABLE, retryable=True)


@lru_cache
def get_embedder_client() -> EmbedderClient:
    settings: EmbedderSettings = get_embedder_settings()
    return EmbedderClient(settings.url, settings.timeout_seconds)
