import logging
from functools import lru_cache

import httpx

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

            data = response.json()
            return data.get("choices", [])[0].get("message", {}).get("content", "").strip()

        except httpx.HTTPStatusError as e:
            logger.error(f"Error LLM: {e.response.status_code} - {e.response.text}")
            raise


@lru_cache
def get_llm() -> LLM:
    """FastAPI dependency: a single shared LLM client (one HTTPX connection pool)."""
    return LLM()
