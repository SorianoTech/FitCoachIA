"""LLM access through LangChain: any OpenAI-compatible chat-completions API."""

import logging
from typing import Any

import httpx
import openai
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from rag_doc.config import RagSettings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The provider failed or returned something unusable."""


def build_chat_model(settings: RagSettings) -> ChatOpenAI:
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    options: dict[str, Any] = {}
    if settings.llm_reasoning_effort == "default":
        options["temperature"] = 0.2
    else:
        # Reasoning models (gpt-5*) reject a custom temperature and spend max_tokens on reasoning
        options["reasoning_effort"] = settings.llm_reasoning_effort
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        **options,
    )


class LLMClient:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def complete(self, messages: list[BaseMessage]) -> str:
        try:
            response = await self._model.ainvoke(messages)
        except (openai.OpenAIError, httpx.HTTPError, ValidationError, KeyError, TypeError) as exc:
            logger.error("LLM call failed: %s", type(exc).__name__)
            raise LLMError("provider error") from exc
        content = response.content
        if not isinstance(content, str) or not content.strip():
            raise LLMError("empty or non-text completion")
        return content.strip()
