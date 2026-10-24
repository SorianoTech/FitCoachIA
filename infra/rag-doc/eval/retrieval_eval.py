"""Offline retrieval eval: chunking/top_k/min_score variants over the gold set, no LLM cost.

Run with `make rag-eval` (CPU/RAM limited); see docs/rag-doc.md, "Evaluación de retrieval".
"""

import argparse
import gc
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import torch
from rag_doc.chunking import Chunk
from rag_doc.config import RagSettings, get_settings
from rag_doc.embeddings import build_embedder
from rag_doc.indexer import build_chunks
from rag_doc.sources import load_sources

GOLD = Path(__file__).with_name("gold_set.jsonl")
VARIANTS = {
    "base (1200/0/0)": dict(max_chars=1200, min_chars=0, overlap=0),
    "min300": dict(max_chars=1200, min_chars=300, overlap=0),
    "min300+ov200": dict(max_chars=1200, min_chars=300, overlap=200),
    "800/min250": dict(max_chars=800, min_chars=250, overlap=0),
    "800/min250+ov150": dict(max_chars=800, min_chars=250, overlap=150),
    "1600/min400": dict(max_chars=1600, min_chars=400, overlap=0),
}


def is_hit(chunk: Chunk, case: dict) -> bool:
    if chunk.source != case["source"]:
        return False
    needle = case["heading"].lower()
    return needle in chunk.heading.lower() or needle in chunk.text.lower()


def evaluate(embedder: Any, chunks: list[Chunk], cases: list[dict], queries: np.ndarray):
    matrix = np.array(embedder.embed_passages([c.embed_text for c in chunks]))
    scores = queries @ matrix.T
    on_topic = [i for i, c in enumerate(cases) if not c.get("offtopic")]
    result = {"chunks": len(chunks), "hit@1": 0, "hit@3": 0, "hit@5": 0, "mrr": 0.0}
    for i in on_topic:
        order = np.argsort(-scores[i])
        rank = next((r for r, j in enumerate(order[:20], 1) if is_hit(chunks[j], cases[i])), None)
        for k in (1, 3, 5):
            result[f"hit@{k}"] += bool(rank and rank <= k)
        result["mrr"] += 1 / rank if rank else 0
    for key in ("hit@1", "hit@3", "hit@5", "mrr"):
        result[key] = round(result[key] / len(on_topic), 3)
    top = scores.max(axis=1)
    result["top_on"] = round(float(min(top[i] for i in on_topic)), 3)
    off = [i for i, c in enumerate(cases) if c.get("offtopic")]
    result["top_off"] = round(float(max(top[i] for i in off)), 3) if off else None
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        default="",
        help="Comma-separated variant names to run (default: all).",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=int(os.environ.get("EVAL_THREADS", "2")),
        help="Torch CPU threads (default: EVAL_THREADS or 2).",
    )
    return parser.parse_args(argv)


def select_variants(raw: str) -> dict[str, dict]:
    if not raw.strip():
        return VARIANTS
    names = [n.strip() for n in raw.split(",") if n.strip()]
    unknown = [n for n in names if n not in VARIANTS]
    if unknown:
        raise SystemExit(f"Unknown variants: {unknown}. Available: {list(VARIANTS)}")
    return {n: VARIANTS[n] for n in names}


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    variants = select_variants(args.variants)
    torch.set_num_threads(max(1, args.threads))
    settings = get_settings()
    cases = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    embedder = build_embedder(settings)
    queries = np.array([embedder.embed_query(c["question"]) for c in cases])
    root = Path(settings.corpus_root)
    sources = load_sources(Path(settings.sources_file), root)
    print(f"{'variant':20} {'chunks':>6} {'h@1':>5} {'h@3':>5} {'h@5':>5} {'mrr':>6} {'minOn':>6} {'maxOff':>6}")
    results: dict[str, dict] = {}
    for name, params in variants.items():
        chunks = build_chunks(sources, root, **params)
        r = evaluate(embedder, chunks, cases, queries)
        results[name] = {**r, "params": params}
        print(
            f"{name:20} {r['chunks']:>6} {r['hit@1']:>5} {r['hit@3']:>5} {r['hit@5']:>5} "
            f"{r['mrr']:>6} {r['top_on']:>6} {r['top_off']:>6}"
        )
        sys.stdout.flush()
        del chunks
        gc.collect()
    print(f"Saved: {save_results(settings, results, len(cases))}")


def save_results(settings: RagSettings, results: dict[str, dict], cases: int) -> Path:
    now = datetime.now(UTC)
    model_slug = re.sub(r"[^A-Za-z0-9._-]+", "-", settings.embedding_model)
    out_dir = Path(os.environ.get("EVAL_OUTPUT_DIR", "/app/results"))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now:%Y%m%dT%H%M%SZ}_{model_slug}.json"
    payload = {
        "timestamp": now.isoformat(),
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
        "dimensions": settings.embedding_dimensions,
        "cases": cases,
        "variants": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
