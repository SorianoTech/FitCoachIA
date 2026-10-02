import json
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from fitcoach.domain.entities import IAInput, IAMessage
from fitcoach.infrastructure.config.settings import IASettings
from fitcoach.service.llm.llm_caller import LLM


@pytest.fixture
def settings() -> IASettings:
    return IASettings(
        base_url="http://test-llm:9999",
        token="test-token",  # noqa: S106
        model="test-model",
        temperature=0.7,
        timeout_seconds=30,
        max_tokens=128,
    )


def _response(payload: object) -> MagicMock:
    """Respuesta 2xx cuyo cuerpo es `payload` serializado (como una real)."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    response.text = json.dumps(payload)
    return response


def _non_json_response(body: str) -> MagicMock:
    """Respuesta 2xx con un cuerpo que no es JSON (p. ej. un proxy devolviendo HTML)."""
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.side_effect = json.JSONDecodeError("Expecting value", body, 0)
    response.text = body
    return response


def _ok_response(content: str) -> MagicMock:
    return _response({"choices": [{"message": {"content": content}}]})


class TestLLMChat:
    @pytest.mark.asyncio
    async def test_chat_posts_settings_defaults_and_returns_stripped_content(
        self, settings: IASettings
    ) -> None:
        llm = LLM(settings=settings)
        llm.client.post = AsyncMock(return_value=_ok_response("  hola  "))
        messages = IAInput([IAMessage(role="user", message="hi")])

        result = await llm.chat(messages=messages)

        assert result == "hola"
        llm.client.post.assert_awaited_once_with(
            "http://test-llm:9999/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": messages.get_input(),
                "temperature": 0.7,
                "max_tokens": 128,
            },
        )

    @pytest.mark.asyncio
    async def test_chat_reraises_http_status_error(self, settings: IASettings) -> None:
        llm = LLM(settings=settings)
        request = httpx.Request("POST", "http://test-llm:9999/v1/chat/completions")
        error_response = httpx.Response(500, text="boom", request=request)
        llm.client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "server error", request=request, response=error_response
            )
        )
        messages = IAInput([IAMessage(role="user", message="hi")])

        with pytest.raises(httpx.HTTPStatusError):
            await llm.chat(messages=messages)

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param({}, id="sin_choices"),
            pytest.param({"choices": []}, id="choices_vacio"),
            pytest.param({"choices": [{}]}, id="sin_message"),
            pytest.param({"choices": [{"message": {}}]}, id="sin_content"),
            pytest.param({"choices": "texto"}, id="choices_no_es_lista"),
            pytest.param({"choices": [{"message": {"content": None}}]}, id="content_null"),
        ],
    )
    @pytest.mark.asyncio
    async def test_chat_returns_empty_string_when_payload_is_malformed(
        self, settings: IASettings, payload: object
    ) -> None:
        llm = LLM(settings=settings)
        llm.client.post = AsyncMock(return_value=_response(payload))

        result = await llm.chat(messages=IAInput([IAMessage(role="user", message="hi")]))

        assert result == ""

    @pytest.mark.asyncio
    async def test_chat_logs_the_body_when_shape_is_unexpected(
        self, settings: IASettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        llm = LLM(settings=settings)
        llm.client.post = AsyncMock(return_value=_response({"error": "quota exceeded"}))

        with caplog.at_level(logging.ERROR):
            result = await llm.chat(messages=IAInput([IAMessage(role="user", message="hi")]))

        assert result == ""
        assert "quota exceeded" in caplog.text

    @pytest.mark.asyncio
    async def test_chat_returns_empty_string_when_body_is_not_json(
        self, settings: IASettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        llm = LLM(settings=settings)
        llm.client.post = AsyncMock(return_value=_non_json_response("<html>502 Bad Gateway</html>"))

        with caplog.at_level(logging.ERROR):
            result = await llm.chat(messages=IAInput([IAMessage(role="user", message="hi")]))

        assert result == ""
        assert "502 Bad Gateway" in caplog.text

    @pytest.mark.asyncio
    async def test_chat_logs_the_type_when_content_is_not_text(
        self, settings: IASettings, caplog: pytest.LogCaptureFixture
    ) -> None:
        llm = LLM(settings=settings)
        llm.client.post = AsyncMock(
            return_value=_response({"choices": [{"message": {"content": None}}]})
        )

        with caplog.at_level(logging.ERROR):
            result = await llm.chat(messages=IAInput([IAMessage(role="user", message="hi")]))

        assert result == ""
        assert "NoneType" in caplog.text
