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


def chunk_markdown(source: str, markdown: str, max_chars: int = 1200) -> list[Chunk]:
    """Split ``markdown`` by headings, then by paragraphs when a section is too long."""
    chunks: list[Chunk] = []
    for heading, body in _sections(markdown):
        for piece in _split_body(body, max_chars):
            chunks.append(Chunk(source, len(chunks), heading, piece))
    return chunks


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


def _split_body(body: str, max_chars: int) -> list[str]:
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
            current = ""
        if len(paragraph) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars))
            continue
        current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces
