from pathlib import Path

import pytest
from rag_doc.sources import SourcesError, load_sources


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# A")
    (tmp_path / "docs" / "b.md").write_text("# B")
    (tmp_path / "docs" / "notes.txt").write_text("x")
    (tmp_path / "docs" / ".env.md").write_text("SECRET=1")
    return tmp_path


def _manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "sources.yml"
    manifest.write_text(content)
    return manifest


def test_load_sources_returns_validated_relative_paths(corpus: Path) -> None:
    manifest = _manifest(corpus, "files:\n  - docs/a.md\n  - docs/b.md\n")

    assert load_sources(manifest, corpus) == ["docs/a.md", "docs/b.md"]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("docs/notes.txt", "Only relative .md"),
        ("docs/.env.md", "Env files"),
        ("../outside.md", "escapes"),
        ("/etc/passwd.md", "Only relative .md"),
        ("docs/missing.md", "not found"),
    ],
)
def test_load_sources_rejects_unsafe_entries(corpus: Path, entry: str, message: str) -> None:
    manifest = _manifest(corpus, f"files:\n  - {entry}\n")

    with pytest.raises(SourcesError, match=message):
        load_sources(manifest, corpus)


@pytest.mark.parametrize(
    "content",
    ["", "files: []", "other: 1", "files:\n  - docs/a.md\n  - docs/a.md\n", "files: [: bad"],
)
def test_load_sources_rejects_malformed_manifest(corpus: Path, content: str) -> None:
    manifest = _manifest(corpus, content)

    with pytest.raises(SourcesError):
        load_sources(manifest, corpus)


def test_load_sources_fails_when_manifest_is_missing(corpus: Path) -> None:
    with pytest.raises(SourcesError, match="Cannot read"):
        load_sources(corpus / "nope.yml", corpus)
