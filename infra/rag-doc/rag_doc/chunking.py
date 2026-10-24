"""Heading-aware Markdown chunking."""

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class Chunk:
    source: str
    index: int
    heading: str
    text: str

    @property
    def embed_text(self) -> str:
        """Text sent to the embedder: the heading path gives the passage its context."""
        return f"{self.heading}\n{self.text}" if self.heading else self.text


def chunk_markdown(
    source: str, markdown: str, max_chars: int = 1200, min_chars: int = 0, overlap: int = 0
) -> list[Chunk]:
    """Split ``markdown`` by headings; merge tiny sections, split long ones with overlap."""
    chunks: list[Chunk] = []
    for heading, body in _merge_small(_sections(markdown), max_chars, min_chars):
        for piece in _split_body(body, max_chars, overlap):
            chunks.append(Chunk(source, len(chunks), heading, piece))
    return chunks


def _merge_small(
    sections: list[tuple[str, str]], max_chars: int, min_chars: int
) -> list[tuple[str, str]]:
    """Fold a section shorter than ``min_chars`` into the next one, keeping its heading in the text."""
    if min_chars <= 0:
        return sections
    merged: list[tuple[str, str]] = []
    pending: tuple[str, str] | None = None
    for heading, body in sections:
        if pending is not None:
            joined = f"{pending[1]}\n\n{heading}\n{body}"
            if len(joined) <= max_chars:
                heading, body = pending[0], joined
            else:
                merged.append(pending)
            pending = None
        if len(body) < min_chars:
            pending = (heading, body)
        else:
            merged.append((heading, body))
    if pending is not None:
        merged.append(pending)
    return merged


def _sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    path: list[tuple[int, str]] = []
    buffer: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            sections.append((" > ".join(title for _, title in path), body))
        buffer.clear()

    for line in markdown.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, match.group(2)))
        else:
            buffer.append(line)
    flush()
    return sections


def _split_body(body: str, max_chars: int, overlap: int = 0) -> list[str]:
    if len(body) <= max_chars:
        return [body]
    pieces: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > max_chars:
            pieces.append(current)
            current = _tail(current, overlap)
        if len(paragraph) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_split_long(paragraph, max_chars))
            continue
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current and (not pieces or current != _tail(pieces[-1], overlap)):
        pieces.append(current)
    return pieces


def _tail(piece: str, overlap: int) -> str:
    """Last paragraph of ``piece`` when it fits in ``overlap``: context carried to the next chunk."""
    if overlap <= 0:
        return ""
    last = piece.rsplit("\n\n", 1)[-1]
    return last if len(last) <= overlap else ""


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    """Cut an oversized paragraph at line ends, then at sentence ends, never mid-word."""
    pieces: list[str] = []
    current = ""
    for unit in re.split(r"(?<=\n)|(?<=[.!?])\s+", paragraph):
        unit = unit.strip("\n ") if not current else unit
        while len(unit) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(unit[:max_chars])
            unit = unit[max_chars:]
        if current and len(current) + len(unit) + 1 > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current} {unit}".strip() if current else unit
    if current:
        pieces.append(current)
    return pieces
