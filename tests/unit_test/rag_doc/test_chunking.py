from rag_doc.chunking import chunk_markdown

DOC = """# Titulo

Intro del documento.

## Seccion A

Texto A.

```bash
# esto no es un encabezado
make up
```

### Sub A1

Texto A1.

## Seccion B

Texto B.
"""


def test_chunk_markdown_keeps_heading_path_per_section() -> None:
    chunks = chunk_markdown("docs/x.md", DOC)

    headings = [chunk.heading for chunk in chunks]
    assert headings == [
        "Titulo",
        "Titulo > Seccion A",
        "Titulo > Seccion A > Sub A1",
        "Titulo > Seccion B",
    ]
    assert [chunk.index for chunk in chunks] == [0, 1, 2, 3]


def test_chunk_markdown_ignores_headings_inside_code_fences() -> None:
    chunks = chunk_markdown("docs/x.md", DOC)

    section_a = chunks[1]
    assert "# esto no es un encabezado" in section_a.text
    assert all("esto no es un encabezado" not in chunk.heading for chunk in chunks)


def test_chunk_markdown_splits_long_sections_by_paragraph() -> None:
    body = "\n\n".join(f"parrafo {i} " + "x" * 50 for i in range(10))

    chunks = chunk_markdown("docs/x.md", f"# T\n\n{body}", max_chars=200)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 200 for chunk in chunks)
    assert {chunk.heading for chunk in chunks} == {"T"}


def test_chunk_markdown_hard_splits_a_single_huge_paragraph() -> None:
    chunks = chunk_markdown("docs/x.md", "# T\n\n" + "y" * 500, max_chars=200)

    assert [len(chunk.text) for chunk in chunks] == [200, 200, 100]


def test_chunk_markdown_returns_nothing_for_empty_document() -> None:
    assert chunk_markdown("docs/x.md", "") == []
    assert chunk_markdown("docs/x.md", "# Solo titulo\n\n") == []


def test_embed_text_prefixes_the_heading_path() -> None:
    chunk = chunk_markdown("docs/x.md", "# T\n\ncuerpo")[0]

    assert chunk.embed_text == "T\ncuerpo"
