from typing import Any

import pytest
from pydantic import SecretStr
from rag_doc import embeddings
from rag_doc.config import RagSettings
from rag_doc.embeddings import Embedder, OpenAIEmbedder, build_embedder


def _settings(**overrides: Any) -> RagSettings:
    return RagSettings(_env_file=None, **overrides)  # type: ignore[call-arg]


class _FakeClient:
    def __init__(self, size: int) -> None:
        self.size = size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.size for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * self.size


def _openai_embedder(client_size: int, dimensions: int = 4) -> OpenAIEmbedder:
    embedder = OpenAIEmbedder("m", dimensions, "sk-test", "https://api.example/v1", 5.0)
    embedder._client = _FakeClient(client_size)  # type: ignore[assignment]
    return embedder


def test_build_embedder_defaults_to_local_e5() -> None:
    assert isinstance(build_embedder(_settings()), Embedder)


def test_build_embedder_openai_falls_back_to_llm_key() -> None:
    settings = _settings(embedding_provider="openai", llm_api_key=SecretStr("sk-llm"))

    assert isinstance(build_embedder(settings), embeddings.OpenAIEmbedder)


def test_build_embedder_openai_without_any_key_fails() -> None:
    with pytest.raises(RuntimeError, match="RAG_EMBEDDING_API_KEY"):
        build_embedder(_settings(embedding_provider="openai"))


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ValueError, match="embedding_provider"):
        _settings(embedding_provider="other")


def test_openai_embedder_returns_vectors_of_configured_dimensions() -> None:
    embedder = _openai_embedder(client_size=4)

    assert embedder.embed_query("hola") == [0.1] * 4
    assert len(embedder.embed_passages(["a", "b"])) == 2


def test_openai_embedder_rejects_wrong_dimensions() -> None:
    embedder = _openai_embedder(client_size=3)

    with pytest.raises(RuntimeError, match="expected 4"):
        embedder.embed_passages(["a"])
