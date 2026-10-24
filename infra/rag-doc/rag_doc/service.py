"""Answer use case: retrieve passages, compose the prompt, ask the LLM."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from rag_doc.prompt import build_messages
from rag_doc.texts import NO_CONTEXT_ANSWER

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


class _Store(Protocol):
    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]: ...


class _LLM(Protocol):
    async def complete(self, messages: list[BaseMessage]) -> str: ...


@dataclass(frozen=True)
class Source:
    source: str
    heading: str
    score: float


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[Source]


class AnswerService:
    def __init__(
        self, embedder: _Embedder, store: _Store, llm: _LLM, top_k: int, min_score: float
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._llm = llm
        self._top_k = top_k
        self._min_score = min_score

    async def ask(self, question: str, history: list[dict[str, str]]) -> Answer:
        vector = await asyncio.to_thread(self._embedder.embed_query, question)
        hits = await asyncio.to_thread(self._store.search, vector, self._top_k)
        passages = [hit for hit in hits if hit["score"] >= self._min_score]
        if not passages:
            logger.info("No passage above min_score for the question")
            return Answer(NO_CONTEXT_ANSWER, [])
        answer = await self._llm.complete(build_messages(question, history, passages))
        return Answer(answer, _unique_sources(passages))


def _unique_sources(passages: list[dict[str, Any]]) -> list[Source]:
    seen: set[tuple[str, str]] = set()
    sources: list[Source] = []
    for passage in passages:
        key = (passage["source"], passage["heading"])
        if key not in seen:
            seen.add(key)
            sources.append(Source(passage["source"], passage["heading"], passage["score"]))
    return sources
