from pathlib import Path

import pytest
from rag_doc.chunking import Chunk
from rag_doc.config import RagSettings
from rag_doc.indexer import run_index
from rag_doc.sources import SourcesError
from rag_doc.store import point_id


class FakeEmbedder:
    dimensions = 3

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.dimensions: int | None = None
        self.chunks: list[Chunk] = []

    def ensure_collection(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def replace_all(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        assert len(chunks) == len(vectors)
        self.chunks = chunks


def _settings(tmp_path: Path, manifest_body: str) -> RagSettings:
    manifest = tmp_path / "sources.yml"
    manifest.write_text(manifest_body)
    return RagSettings(_env_file=None, corpus_root=str(tmp_path), sources_file=str(manifest))


def test_run_index_embeds_and_stores_every_whitelisted_chunk(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# A\n\ntexto\n\n## B\n\nmas")
    store = FakeStore()

    report = run_index(_settings(tmp_path, "files:\n  - a.md\n"), FakeEmbedder(), store)

    assert (report.files, report.chunks) == (1, 2)
    assert store.dimensions == 3
    assert {chunk.source for chunk in store.chunks} == {"a.md"}


def test_run_index_refuses_to_wipe_the_index_with_an_empty_corpus(tmp_path: Path) -> None:
    (tmp_path / "empty.md").write_text("# Solo titulo")
    store = FakeStore()

    with pytest.raises(SourcesError, match="no chunks"):
        run_index(_settings(tmp_path, "files:\n  - empty.md\n"), FakeEmbedder(), store)

    assert store.chunks == []


def test_point_id_is_deterministic_and_unique_per_chunk() -> None:
    first = Chunk("docs/a.md", 0, "T", "x")

    assert point_id(first) == point_id(Chunk("docs/a.md", 0, "otro", "y"))
    assert point_id(first) != point_id(Chunk("docs/a.md", 1, "T", "x"))
    assert point_id(first) != point_id(Chunk("docs/b.md", 0, "T", "x"))
