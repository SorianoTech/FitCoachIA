"""Whitelist of indexable files: the only way a document can reach the public RAG."""

from pathlib import Path

import yaml


class SourcesError(ValueError):
    """The whitelist is malformed or points to something that must not be indexed."""


def load_sources(manifest: Path, corpus_root: Path) -> list[str]:
    """Return the validated relative paths listed in ``manifest``."""
    try:
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourcesError(f"Cannot read whitelist {manifest}: {exc}") from exc

    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list) or not files:
        raise SourcesError("The whitelist needs a non-empty 'files' list")

    root = corpus_root.resolve()
    validated: list[str] = []
    for entry in files:
        validated.append(_validate_entry(entry, root))
    if len(set(validated)) != len(validated):
        raise SourcesError("The whitelist contains duplicated files")
    return validated


def _validate_entry(entry: object, root: Path) -> str:
    if not isinstance(entry, str) or not entry.strip():
        raise SourcesError(f"Invalid whitelist entry: {entry!r}")
    path = Path(entry)
    if path.is_absolute() or path.suffix.lower() != ".md":
        raise SourcesError(f"Only relative .md files are allowed: {entry}")
    if path.name.lower().startswith(".env"):
        raise SourcesError(f"Env files can never be indexed: {entry}")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise SourcesError(f"Path escapes the corpus root: {entry}")
    if not resolved.is_file():
        raise SourcesError(f"Whitelisted file not found: {entry}")
    return path.as_posix()
