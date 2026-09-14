import json
import logging
from functools import lru_cache

import httpx

from fitcoach.domain.constants import Constants
from fitcoach.domain.entities import IAInput
from fitcoach.infrastructure.config.settings import IASettings, get_ia_settings

logger = logging.getLogger(__name__)


class LLM:
    def __init__(self, settings: IASettings | None = None) -> None:
        self._settings = settings or get_ia_settings()

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.token}",
            "User-Agent": "FitCoachIA-Bot/1.0",
        }
        self.client = httpx.AsyncClient(
            timeout=self._settings.timeout_seconds,
            headers=self.headers,
        )

    async def chat(self, messages: IAInput) -> str:
        """Llamar endpoint /v1/chat/completions (OpenAI-compatible)"""
        try:
            response = await self.client.post(
                f"{self._settings.base_url}/v1/chat/completions",
                json={
                    "model": self._settings.model,
                    "messages": messages.get_input(),
                    "temperature": self._settings.temperature,
                    "max_tokens": self._settings.max_tokens,
                },
            )
            response.raise_for_status()
            return self._extract_content(response)

        except httpx.HTTPStatusError as e:
            logger.error(f"Error LLM: {e.response.status_code} - {e.response.text}")
            raise

    @staticmethod
    def _extract_content(response: httpx.Response) -> str:
        """Texto de una respuesta OpenAI-compatible; "" si la forma no es la esperada.

        Se devuelve "" en lugar de propagar porque el llamante ya trata la respuesta
        vacia como fallo del modelo. Asi la traza dice que venia mal en el cuerpo, en
        vez de un stacktrace que no distingue esto de una caida de red.
        """
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            body = response.text[: Constants.MAX_LOGGED_CHARS]
            logger.error(f"Respuesta del LLM con forma inesperada: {body}")
            return ""

        if not isinstance(content, str):
            # `content: null` es lo que devuelve el modelo cuando responde con
            # tool_calls en lugar de texto.
            logger.error(f"'content' no es texto: tipo {type(content).__name__}")
            return ""

        return content.strip()


@lru_cache
def get_llm() -> LLM:
    """FastAPI dependency: a single shared LLM client (one HTTPX connection pool)."""
    return LLM()
