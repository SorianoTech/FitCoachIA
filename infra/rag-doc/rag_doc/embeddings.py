"""Embeddings: local multilingual E5 (CPU) or an OpenAI-compatible API."""

from typing import Any

from rag_doc.config import RagSettings


class Embedder:
    """E5 models need the ``query:`` / ``passage:`` prefixes to land in the same space."""

    def __init__(self, model_name: str, dimensions: int) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._model: Any = None

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self._model_name)
            actual = model.get_sentence_embedding_dimension()
            if actual != self._dimensions:
                raise RuntimeError(
                    f"Model {self._model_name} produces {actual}-dim vectors, "
                    f"expected {self._dimensions}"
                )
            self._model = model
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([f"passage: {text}" for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}"])[0]

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True, batch_size=16)
        return [[float(value) for value in vector] for vector in vectors]


class OpenAIEmbedder:
    """OpenAI-compatible embeddings API; no E5 prefixes, vectors are L2-normalised server-side."""

    def __init__(
        self, model_name: str, dimensions: int, api_key: str, base_url: str, timeout: float
    ) -> None:
        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        self._dimensions = dimensions
        self._client = OpenAIEmbeddings(
            model=model_name,
            dimensions=dimensions,
            api_key=SecretStr(api_key),
            base_url=base_url,
            timeout=timeout,
            max_retries=2,
        )

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._check(self._client.embed_documents(texts))

    def embed_query(self, text: str) -> list[float]:
        return self._check([self._client.embed_query(text)])[0]

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise RuntimeError(
                    f"Embedding API returned {len(vector)}-dim vectors, expected {self._dimensions}"
                )
        return vectors


def build_embedder(settings: RagSettings) -> Embedder | OpenAIEmbedder:
    if settings.embedding_provider == "local":
        return Embedder(settings.embedding_model, settings.embedding_dimensions)
    key = settings.embedding_api_key or settings.llm_api_key
    if key is None or not key.get_secret_value():
        raise RuntimeError("RAG_EMBEDDING_API_KEY (or RAG_LLM_API_KEY) is required for openai")
    return OpenAIEmbedder(
        settings.embedding_model,
        settings.embedding_dimensions,
        key.get_secret_value(),
        settings.embedding_base_url,
        settings.embedding_timeout_seconds,
    )
