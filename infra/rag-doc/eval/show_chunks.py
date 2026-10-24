"""Shows the chunks rag-doc retrieves from Qdrant for a question (no LLM call).

Run it inside the running service so it reaches Qdrant with the real settings:
    docker exec -i rag-doc python - "¿cómo funciona el scheduler?" < infra/rag-doc/eval/show_chunks.py
"""

import argparse
import sys

from rag_doc.config import get_settings
from rag_doc.embeddings import build_embedder
from rag_doc.store import VectorStore

PREVIEW_CHARS = 300


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question exactly as the user would ask it.")
    parser.add_argument(
        "--top-k", type=int, default=None, help="Chunks to retrieve (default: RAG_TOP_K)."
    )
    parser.add_argument("--full", action="store_true", help="Print the whole chunk text.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    from qdrant_client import QdrantClient

    args = parse_args(argv)
    settings = get_settings()
    top_k = args.top_k or settings.top_k
    embedder = build_embedder(settings)
    store = VectorStore(QdrantClient(url=settings.qdrant_url), settings.qdrant_collection)
    hits = store.search(embedder.embed_query(args.question), top_k)

    out = sys.stdout.write
    out(f"Question: {args.question}\n")
    out(f"top_k={top_k} min_score={settings.min_score} collection={settings.qdrant_collection}\n")
    if not hits:
        out("No chunks returned (empty collection? run `make rag-index`).\n")
        return
    for rank, hit in enumerate(hits, start=1):
        sent = hit["score"] >= settings.min_score
        text = hit["text"] if args.full else hit["text"][:PREVIEW_CHARS].replace("\n", " ")
        out(f"\n[{rank}] score={hit['score']:.3f} {'sent to LLM' if sent else 'below min_score'}\n")
        out(f"    {hit['source']} — {hit['heading'] or '(no heading)'}\n")
        out(f"    {text}{'' if args.full or len(hit['text']) <= PREVIEW_CHARS else '…'}\n")


if __name__ == "__main__":
    main()
