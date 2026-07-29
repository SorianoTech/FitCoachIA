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


def _ok_response(content: str) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    return response


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
