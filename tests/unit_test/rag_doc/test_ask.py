from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import BaseMessage
from rag_doc.api import get_answer_service, router
from rag_doc.limits import RateLimiter
from rag_doc.llm import LLMError
from rag_doc.service import AnswerService
from rag_doc.texts import NO_CONTEXT_ANSWER

HITS = [
    {"score": 0.9, "source": "docs/a.md", "heading": "A", "text": "uno"},
    {"score": 0.8, "source": "docs/a.md", "heading": "A", "text": "dos"},
    {"score": 0.3, "source": "docs/b.md", "heading": "B", "text": "tres"},
]


class FakeEmbedder:
    def embed_query(self, text: str) -> list[float]:
        return [1.0]


class FakeStore:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits

    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        return self._hits[:limit]


class FakeLLM:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[list[BaseMessage]] = []

    async def complete(self, messages: list[BaseMessage]) -> str:
        self.calls.append(messages)
        if self.error:
            raise self.error
        return "respuesta [1]"


def _service(hits: list[dict[str, Any]], llm: FakeLLM, min_score: float = 0.5) -> AnswerService:
    return AnswerService(FakeEmbedder(), FakeStore(hits), llm, top_k=5, min_score=min_score)


@pytest.mark.asyncio
async def test_ask_answers_with_deduplicated_sources_above_min_score() -> None:
    llm = FakeLLM()

    result = await _service(HITS, llm).ask("que es", [])

    assert result.answer == "respuesta [1]"
    assert [(s.source, s.heading) for s in result.sources] == [("docs/a.md", "A")]
    assert "tres" not in str(llm.calls[0][0].content)


@pytest.mark.asyncio
async def test_ask_does_not_call_the_llm_without_relevant_passages() -> None:
    llm = FakeLLM()

    result = await _service(HITS, llm, min_score=0.95).ask("paella", [])

    assert result.answer == NO_CONTEXT_ANSWER
    assert result.sources == []
    assert llm.calls == []


def _client(service: AnswerService) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_answer_service] = lambda: service
    app.state.rate_limiter = RateLimiter(per_minute=1000, daily_cap=1000)
    return TestClient(app)


def test_post_ask_returns_answer_and_sources() -> None:
    client = _client(_service(HITS, FakeLLM()))

    response = client.post("/api/ask", json={"question": "que es", "history": []})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "respuesta [1]"
    assert body["sources"][0]["source"] == "docs/a.md"


def test_post_ask_maps_provider_failures_to_502() -> None:
    client = _client(_service(HITS, FakeLLM(LLMError("down"))))

    response = client.post("/api/ask", json={"question": "que es"})

    assert response.status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 501},
        {},
        {"question": "ok", "history": [{"role": "system", "content": "x"}]},
        {"question": "ok", "history": [{"role": "user", "content": "x"}] * 7},
        {"question": "ok", "history": [{"role": "user", "content": "x" * 1001}]},
    ],
)
def test_post_ask_rejects_invalid_payloads(payload: dict[str, Any]) -> None:
    client = _client(_service(HITS, FakeLLM()))

    assert client.post("/api/ask", json=payload).status_code == 422
