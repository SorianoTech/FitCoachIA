"""Generate the PWA icons (pure stdlib). Run: python infra/rag-doc/make_icons.py"""

import struct
import zlib
from pathlib import Path

BRAND = (0, 85, 255)
WHITE = (255, 255, 255)
OUT = Path(__file__).parent / "rag_doc" / "static" / "icons"


def _png(size: int, pixel) -> bytes:
    rows = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y, size)) for x in range(size)) for y in range(size)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _document(margin: float):
    """White page with text lines on the brand colour; content inside the safe zone."""

    def pixel(x: int, y: int, size: int):
        u, v = x / size, y / size
        if margin <= u <= 1 - margin and margin <= v <= 1 - margin:
            inner_v = (v - margin) / (1 - 2 * margin)
            inner_u = (u - margin) / (1 - 2 * margin)
            if any(
                a <= inner_v <= a + 0.08 and 0.15 <= inner_u <= 0.85 for a in (0.25, 0.45, 0.65)
            ):
                return BRAND
            return WHITE
        return BRAND

    return pixel


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon-192x192.png").write_bytes(_png(192, _document(0.2)))
    (OUT / "icon-512x512.png").write_bytes(_png(512, _document(0.2)))
    (OUT / "maskable-512x512.png").write_bytes(_png(512, _document(0.3)))
