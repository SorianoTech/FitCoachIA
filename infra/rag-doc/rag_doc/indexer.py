"""Indexing job: whitelist -> chunks -> embeddings -> Qdrant. Run with ``make rag-index``."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rag_doc.chunking import Chunk, chunk_markdown
from rag_doc.config import RagSettings, get_settings
from rag_doc.embeddings import build_embedder
from rag_doc.sources import SourcesError, load_sources
from rag_doc.store import VectorStore

logger = logging.getLogger(__name__)


class _Embedder(Protocol):
    @property
    def dimensions(self) -> int: ...

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...


class _Store(Protocol):
    def ensure_collection(self, dimensions: int) -> None: ...

    def replace_all(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...


@dataclass(frozen=True)
class IndexReport:
    files: int
    chunks: int


def build_chunks(
    sources: list[str], corpus_root: Path, max_chars: int, min_chars: int = 0, overlap: int = 0
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for source in sources:
        text = (corpus_root / source).read_text(encoding="utf-8")
        chunks.extend(chunk_markdown(source, text, max_chars, min_chars, overlap))
    return chunks


def run_index(settings: RagSettings, embedder: _Embedder, store: _Store) -> IndexReport:
    corpus_root = Path(settings.corpus_root)
    sources = load_sources(Path(settings.sources_file), corpus_root)
    chunks = build_chunks(
        sources,
        corpus_root,
        settings.chunk_max_chars,
        settings.chunk_min_chars,
        settings.chunk_overlap,
    )
    if not chunks:
        # Refuse to wipe the collection because of an empty corpus
        raise SourcesError("The whitelisted files produced no chunks")
    vectors = embedder.embed_passages([chunk.embed_text for chunk in chunks])
    store.ensure_collection(embedder.dimensions)
    store.replace_all(chunks, vectors)
    logger.info("Indexed %d chunks from %d files", len(chunks), len(sources))
    return IndexReport(files=len(sources), chunks=len(chunks))


def main() -> None:
    from qdrant_client import QdrantClient

    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s [%(levelname)8s] %(name)s - %(message)s",
    )
    embedder = build_embedder(settings)
    store = VectorStore(QdrantClient(url=settings.qdrant_url), settings.qdrant_collection)
    run_index(settings, embedder, store)


if __name__ == "__main__":
    main()
