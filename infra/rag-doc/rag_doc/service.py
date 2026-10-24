"""Answer use case: retrieve passages, compose the prompt, ask the LLM."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from rag_doc.llm import LLMError
from rag_doc.prompt import build_messages, build_rewrite_messages
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
    number: int
    source: str
    heading: str
    score: float


@dataclass(frozen=True)
class Answer:
    answer: str
    sources: list[Source]


class AnswerService:
    def __init__(
        self,
        embedder: _Embedder,
        store: _Store,
        llm: _LLM,
        top_k: int,
        min_score: float,
        rewrite_queries: bool = False,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._llm = llm
        self._top_k = top_k
        self._min_score = min_score
        self._rewrite_queries = rewrite_queries

    async def _search_query(self, question: str, history: list[dict[str, str]]) -> str:
        """Follow-ups ("¿y eso?") are rewritten into standalone questions before the search."""
        if not (self._rewrite_queries and history):
            return question
        try:
            return await self._llm.complete(build_rewrite_messages(question, history))
        except LLMError:
            logger.warning("Query rewrite failed, searching with the raw question")
            return question

    async def ask(self, question: str, history: list[dict[str, str]]) -> Answer:
        query = await self._search_query(question, history)
        vector = await asyncio.to_thread(self._embedder.embed_query, query)
        hits = await asyncio.to_thread(self._store.search, vector, self._top_k)
        passages = [hit for hit in hits if hit["score"] >= self._min_score]
        if not passages:
            logger.info("No passage above min_score for the question")
            return Answer(NO_CONTEXT_ANSWER, [])
        answer = await self._llm.complete(build_messages(question, history, passages))
        return Answer(answer, _numbered_sources(passages))


def _numbered_sources(passages: list[dict[str, Any]]) -> list[Source]:
    # Same 1-based numbering as format_context, so [n] in the answer matches a source.
    return [
        Source(number, passage["source"], passage["heading"], passage["score"])
        for number, passage in enumerate(passages, start=1)
    ]
