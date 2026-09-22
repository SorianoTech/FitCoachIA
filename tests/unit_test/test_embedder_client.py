from collections.abc import Callable
from unittest.mock import patch

import httpx
import pytest

from fitcoach.domain.agent_errors import AgentError, AgentErrorCode
from fitcoach.infrastructure.ia.embedder_client import EmbedderClient
from fitcoach.infrastructure.vectordb.models import EMBEDDING_DIMENSIONS


def _client_with(handler: Callable[[httpx.Request], httpx.Response]) -> EmbedderClient:
    """An EmbedderClient whose AsyncClient is backed by a MockTransport."""
    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    patcher = patch(
        "fitcoach.infrastructure.ia.embedder_client.httpx.AsyncClient", side_effect=factory
    )
    patcher.start()
    return EmbedderClient("http://embedder:8100")


@pytest.fixture(autouse=True)
def _stop_patches() -> object:
    yield
    patch.stopall()


def _vector() -> list[float]:
    return [0.1] * EMBEDDING_DIMENSIONS


class TestEmbed:
    @pytest.mark.asyncio
    async def test_returns_the_vectors_for_each_text(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/embed"
            return httpx.Response(200, json={"vectors": [_vector(), _vector()]})

        vectors = await _client_with(handler).embed(["chest", "back"])

        assert len(vectors) == 2
        assert len(vectors[0]) == EMBEDDING_DIMENSIONS

    @pytest.mark.asyncio
    async def test_does_not_call_the_service_for_an_empty_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
            raise AssertionError("the embedder should not be called")

        assert await _client_with(handler).embed([]) == []

    @pytest.mark.asyncio
    async def test_rejects_a_vector_of_the_wrong_dimension(self) -> None:
        # A different dimension means a different model than the corpus used,
        # so cosine distance would be meaningless.
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"vectors": [[0.1, 0.2, 0.3]]})

        with pytest.raises(AgentError) as exc_info:
            await _client_with(handler).embed(["chest"])

        assert exc_info.value.code is AgentErrorCode.INVALID_OUTPUT
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_rejects_a_response_with_fewer_vectors_than_texts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"vectors": [_vector()]})

        with pytest.raises(AgentError) as exc_info:
            await _client_with(handler).embed(["chest", "back"])

        assert exc_info.value.code is AgentErrorCode.INVALID_OUTPUT

    @pytest.mark.asyncio
    async def test_maps_a_timeout_to_a_retryable_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("too slow")

        with pytest.raises(AgentError) as exc_info:
            await _client_with(handler).embed(["chest"])

        assert exc_info.value.code is AgentErrorCode.TIMEOUT
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_maps_a_connection_failure_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(AgentError) as exc_info:
            await _client_with(handler).embed(["chest"])

        assert exc_info.value.code is AgentErrorCode.UNAVAILABLE

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (503, AgentErrorCode.UNAVAILABLE),
            (500, AgentErrorCode.UNAVAILABLE),
            (429, AgentErrorCode.RATE_LIMITED),
            (422, AgentErrorCode.INVALID_REQUEST),
            (408, AgentErrorCode.TIMEOUT),
        ],
    )
    @pytest.mark.asyncio
    async def test_maps_http_status_codes(self, status_code: int, expected: AgentErrorCode) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json={"detail": "internal detail"})

        with pytest.raises(AgentError) as exc_info:
            await _client_with(handler).embed(["chest"])

        assert exc_info.value.code is expected
        # The upstream body never reaches the caller.
        assert "internal detail" not in str(exc_info.value)
