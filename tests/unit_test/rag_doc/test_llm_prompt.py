from typing import Any

import httpx
import openai
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import SecretStr
from rag_doc.config import RagSettings
from rag_doc.llm import LLMClient, LLMError, build_chat_model
from rag_doc.prompt import build_messages


class FailingModel(GenericFakeChatModel):
    error: Any = None

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error


def _fake(*contents: Any) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=c) for c in contents]))


@pytest.mark.asyncio
async def test_complete_returns_the_stripped_message_content() -> None:
    client = LLMClient(_fake(" hola "))

    assert await client.complete([HumanMessage("x")]) == "hola"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["   ", ["bloque", "no texto"]])
async def test_complete_rejects_empty_or_non_text_completions(content: Any) -> None:
    with pytest.raises(LLMError):
        await LLMClient(_fake(content)).complete([HumanMessage("x")])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=httpx.Request("POST", "https://llm.test")),
        openai.APITimeoutError(request=httpx.Request("POST", "https://llm.test")),
        httpx.ConnectError("down"),
        KeyError("choices"),
    ],
)
async def test_complete_maps_provider_failures_to_llm_error(error: Exception) -> None:
    client = LLMClient(FailingModel(messages=iter([]), error=error))

    with pytest.raises(LLMError):
        await client.complete([HumanMessage("x")])


def test_build_chat_model_uses_the_openai_compatible_settings() -> None:
    settings = RagSettings(
        _env_file=None,
        llm_base_url="https://llm.test/v1",
        llm_api_key=SecretStr("k"),
        llm_model="open-model",
        llm_max_tokens=123,
    )

    model = build_chat_model(settings)

    assert model.model_name == "open-model"
    assert model.max_tokens == 123
    assert model.openai_api_base == "https://llm.test/v1"
    assert model.temperature == 0.2
    assert model.reasoning_effort is None


def test_build_chat_model_for_reasoning_models_omits_temperature() -> None:
    settings = RagSettings(
        _env_file=None,
        llm_api_key=SecretStr("k"),
        llm_model="gpt-5-nano-2025-08-07",
        llm_reasoning_effort="minimal",
    )

    model = build_chat_model(settings)

    assert model.reasoning_effort == "minimal"
    assert model.temperature is None
    assert "temperature" not in model._default_params


def test_build_messages_numbers_the_context_and_keeps_history_order() -> None:
    passages = [
        {"source": "docs/a.md", "heading": "A > B", "text": "texto uno", "score": 0.9},
        {"source": "docs/c.md", "heading": "", "text": "texto dos", "score": 0.8},
    ]
    history = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "resp"}]

    messages = build_messages("pregunta", history, passages)

    assert [type(m) for m in messages] == [SystemMessage, HumanMessage, AIMessage, HumanMessage]
    assert "[1] docs/a.md — A > B\ntexto uno" in str(messages[0].content)
    assert "[2] docs/c.md\ntexto dos" in str(messages[0].content)
    assert messages[-1].content == "pregunta"
