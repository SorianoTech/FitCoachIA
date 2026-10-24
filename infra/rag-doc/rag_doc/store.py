"""Qdrant access: idempotent writes and similarity search."""

import uuid
from typing import Any

from rag_doc.chunking import Chunk

_NAMESPACE = uuid.UUID("6f1c1d0e-5a7e-4c3b-9d5e-2f6a8b7c9d10")


def point_id(chunk: Chunk) -> str:
    """Deterministic id: re-indexing the same chunk overwrites it instead of duplicating."""
    return str(uuid.uuid5(_NAMESPACE, f"{chunk.source}#{chunk.index}"))


class VectorStore:
    def __init__(self, client: Any, collection: str) -> None:
        self._client = client
        self._collection = collection

    def ensure_collection(self, dimensions: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                self._collection,
                vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE),
            )

    def replace_all(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Make the collection contain exactly ``chunks``; any other point is deleted."""
        from qdrant_client.models import Filter, HasIdCondition, PointStruct

        points = [
            PointStruct(
                id=point_id(chunk),
                vector=vector,
                payload={"source": chunk.source, "heading": chunk.heading, "text": chunk.text},
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if points:
            self._client.upsert(self._collection, points=points)
        # Stale chunks of re-indexed files and files removed from the whitelist
        keep = [point.id for point in points]
        self._client.delete(
            self._collection,
            points_selector=Filter(must_not=[HasIdCondition(has_id=keep)]),
        )

    def search(self, vector: list[float], limit: int) -> list[dict[str, Any]]:
        hits = self._client.query_points(
            self._collection, query=vector, limit=limit, with_payload=True
        ).points
        return [{"score": hit.score, **(hit.payload or {})} for hit in hits]
