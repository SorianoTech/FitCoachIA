from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from rag_doc.chunking import chunk_markdown
from rag_doc.llm import LLMError
from rag_doc.service import AnswerService

HITS = [{"score": 0.9, "source": "docs/a.md", "heading": "A", "text": "uno"}]
HISTORY = [{"role": "user", "content": "¿Qué es X?"}, {"role": "assistant", "content": "Es X."}]


class RecordingEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [1.0]


class Store:
    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        return HITS


class ScriptedLLM:
    def __init__(self, rewrite: str | Exception) -> None:
        self.rewrite = rewrite
        self.calls = 0

    async def complete(self, messages: list[BaseMessage]) -> str:
        self.calls += 1
        if self.calls == 1:
            if isinstance(self.rewrite, Exception):
                raise self.rewrite
            return self.rewrite
        return "respuesta"


def _service(embedder: RecordingEmbedder, llm: ScriptedLLM, rewrite: bool) -> AnswerService:
    return AnswerService(embedder, Store(), llm, 5, 0.0, rewrite)


@pytest.mark.asyncio
async def test_follow_up_is_rewritten_before_the_search() -> None:
    embedder = RecordingEmbedder()

    await _service(embedder, ScriptedLLM("¿Por qué no se puede cambiar X?"), True).ask(
        "¿y por qué no?", HISTORY
    )

    assert embedder.queries == ["¿Por qué no se puede cambiar X?"]


@pytest.mark.asyncio
async def test_rewrite_failure_falls_back_to_the_raw_question() -> None:
    embedder = RecordingEmbedder()

    result = await _service(embedder, ScriptedLLM(LLMError("boom")), True).ask("¿y eso?", HISTORY)

    assert embedder.queries == ["¿y eso?"]
    assert result.answer == "respuesta"


@pytest.mark.asyncio
async def test_no_rewrite_without_history_or_when_disabled() -> None:
    embedder = RecordingEmbedder()
    llm = ScriptedLLM("no se usa")

    await _service(embedder, llm, True).ask("pregunta", [])
    await _service(embedder, llm, False).ask("pregunta", HISTORY)

    assert embedder.queries == ["pregunta", "pregunta"]
    assert llm.calls == 2


def test_small_sections_are_merged_keeping_their_headings() -> None:
    markdown = "# T\n\n## A\nuno\n\n## B\ndos\n\n## C\n" + "x" * 400

    chunks = chunk_markdown("a.md", markdown, max_chars=1200, min_chars=100)

    assert len(chunks) == 1
    assert "## B" not in chunks[0].text and "B\ndos" in chunks[0].text


def test_overlap_repeats_the_last_paragraph_in_the_next_chunk() -> None:
    paragraphs = [f"p{i} " + "w" * 90 for i in range(6)]

    chunks = chunk_markdown("a.md", "# T\n\n" + "\n\n".join(paragraphs), max_chars=250, overlap=120)

    assert len(chunks) >= 3
    assert chunks[0].text.split("\n\n")[-1] == chunks[1].text.split("\n\n")[0]


def test_long_paragraph_is_cut_at_sentence_ends() -> None:
    sentence = "Esta es una frase de ejemplo bastante larga para cortar."
    chunks = chunk_markdown("a.md", "# T\n\n" + " ".join([sentence] * 10), max_chars=150)

    assert all(chunk.text.endswith(".") for chunk in chunks)
    assert all(len(chunk.text) <= 150 for chunk in chunks)
