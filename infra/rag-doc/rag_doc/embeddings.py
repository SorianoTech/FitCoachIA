"""Open-source multilingual embeddings (E5 family, CPU)."""

from typing import Any


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
