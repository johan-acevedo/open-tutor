#!/usr/bin/env python3
"""Build and query a local EmbeddingGemma 2 index over a small passage sample.

A bounded proof of the search step, not the production API: exact cosine search
over an explicit, small selection of passages. Weights and the index live outside
Git (~/.cache/huggingface and ``default_index_dir()``).

    bin/with-env uv run --group ml python scripts/search_materials.py prove
    bin/with-env uv run --group ml python scripts/search_materials.py build \\
        --select natural-sciences-and-technology-6:photosynthesis:40 \\
        --select natural-sciences-and-technology-6:electric circuits:40 \\
        --select mathematics-12:sequences and series:40
    bin/with-env uv run --group ml python scripts/search_materials.py query \\
        --query "how does a battery make a lamp light up?" --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from open_tutor.materials.catalogue import DEFAULT_BOOKS_PATH, default_data_dir
from open_tutor.materials.passages import extract_catalogue_passages
from open_tutor.materials.search import (
    MODEL_ID,
    EmbeddingGemmaEmbedder,
    build_index,
    default_index_dir,
    load_index,
    normalize,
    query_index,
    save_index,
)

# A selector is BOOK:SUBSTRING[:CAP] against a passage's heading and breadcrumbs.
DEFAULT_SELECT_CAP = 40
DEFAULT_MAX_PASSAGES = 200


def parse_selector(value: str, default_cap: int = DEFAULT_SELECT_CAP) -> dict:
    """Parse ``BOOK:SUBSTRING[:CAP]``; a trailing all-digit part is the cap."""
    book, _, rest = value.partition(":")
    if not book or not rest:
        raise ValueError(f"Selector needs BOOK:SUBSTRING, got {value!r}")
    cap = default_cap
    head, sep, tail = rest.rpartition(":")
    if sep and tail.isdigit():
        rest, cap = head, int(tail)
    if cap <= 0:
        raise ValueError(f"Selector cap must be positive, got {value!r}")
    return {"book": book, "needle": rest.lower(), "cap": cap}


def _haystack(record: dict) -> str:
    parts = [record.get("heading") or "", *(record.get("breadcrumbs") or [])]
    return " ".join(parts).lower()


def select_records(records: list[dict], selectors: list[dict], max_passages: int) -> list[dict]:
    """Passages matching each selector, in corpus order, capped per selector."""
    chosen: list[dict] = []
    seen: set[str] = set()
    for selector in selectors:
        taken = 0
        for record in records:
            if taken >= selector["cap"] or len(chosen) >= max_passages:
                break
            if record.get("book_id") != selector["book"]:
                continue
            if record["id"] in seen or selector["needle"] not in _haystack(record):
                continue
            seen.add(record["id"])
            chosen.append(record)
            taken += 1
    return chosen


def _records(selectors: list[dict], data_dir: Path, books_path: Path) -> tuple[list[dict], dict]:
    books = sorted({selector["book"] for selector in selectors})
    passages, meta = extract_catalogue_passages(
        data_dir=data_dir, books_path=books_path, book_ids=books
    )
    return [passage.to_dict() for passage in passages], meta


def cmd_prove(args: argparse.Namespace) -> int:
    """One real query and two real documents: is the model loading at all?"""
    started = time.perf_counter()
    embedder = EmbeddingGemmaEmbedder(model_id=args.model)
    documents = [
        (
            "The northern lights",
            "The northern lights are caused by charged particles from the sun "
            "colliding with gases in the atmosphere.",
        ),
        (
            "Baking bread",
            "Bread rises because yeast ferments sugar and releases carbon dioxide "
            "gas into the dough.",
        ),
    ]
    query = "What causes the northern lights?"
    query_vector = normalize([float(value) for value in embedder.encode_query(query)])
    document_vectors = [
        normalize([float(value) for value in vector])
        for vector in embedder.encode_documents([text for _title, text in documents])
    ]
    report = {
        "model": embedder.describe(),
        "query": query,
        "documents": [
            {
                "title": title,
                "text": text,
                "score": round(sum(a * b for a, b in zip(query_vector, vector)), 6),
            }
            for (title, text), vector in zip(documents, document_vectors)
        ],
        "query_vector_head": [round(value, 6) for value in query_vector[:4]],
        "query_norm": round(sum(value * value for value in query_vector) ** 0.5, 6),
        "elapsed_seconds_one_run": round(time.perf_counter() - started, 2),
        "timing_note": "one run including model load and download check; not a benchmark",
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    selectors = [parse_selector(value) for value in args.select]
    records, extraction_meta = _records(selectors, args.data_dir, args.books_json)
    chosen = select_records(records, selectors, args.max_passages)
    if not chosen:
        raise ValueError("The selectors matched no passages; nothing to index")

    embedder = EmbeddingGemmaEmbedder(model_id=args.model)
    corpus = {
        "selectors": [
            {"book": selector["book"], "substring": selector["needle"], "cap": selector["cap"]}
            for selector in selectors
        ],
        "max_passages": args.max_passages,
        "selected_passages": len(chosen),
        "books": sorted({record["book_id"] for record in chosen}),
        "extraction": extraction_meta,
    }
    index = build_index(chosen, embedder, corpus=corpus)
    path = save_index(index, Path(args.index))
    print(
        json.dumps(
            {
                "index": str(path),
                "model": embedder.describe(),
                "vectors": len(index.entries),
                "dimension": index.dimension,
                "skipped_empty_text": index.skipped_empty_text,
                "incomplete_text_passages": sum(1 for entry in index.entries if not entry["text_complete"]),
                "books": corpus["books"],
                "selectors": corpus["selectors"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    index = load_index(Path(args.index))
    embedder = EmbeddingGemmaEmbedder(model_id=args.model or index.model_id)
    report = {
        "index": str(Path(args.index)),
        "model": embedder.describe(),
        "index_model": {"model_id": index.model_id, "model_revision": index.model_revision},
        "indexed_passages": len(index.entries),
        "queries": [
            {"query": query, "results": query_index(index, embedder, query, limit=args.limit)}
            for query in args.query
        ],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prove = sub.add_parser("prove", help="encode one real query and two documents")
    prove.add_argument("--model", default=MODEL_ID)
    prove.set_defaults(func=cmd_prove)

    build = sub.add_parser("build", help="embed a small passage selection into a local index")
    build.add_argument(
        "--select",
        action="append",
        required=True,
        metavar="BOOK:SUBSTRING[:CAP]",
        help=f"passages of one book whose heading/breadcrumbs contain SUBSTRING "
        f"(default cap {DEFAULT_SELECT_CAP}); repeat to build a mixed sample",
    )
    build.add_argument("--index", type=Path, default=default_index_dir())
    build.add_argument("--model", default=MODEL_ID)
    build.add_argument(
        "--max-passages",
        type=int,
        default=DEFAULT_MAX_PASSAGES,
        help="hard cap on total passages in this proof index",
    )
    build.add_argument("--data-dir", type=Path, default=default_data_dir())
    build.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    build.set_defaults(func=cmd_build)

    query = sub.add_parser("query", help="rank indexed passages for one or more queries")
    query.add_argument("--query", action="append", required=True, help="query text; repeat")
    query.add_argument("--index", type=Path, default=default_index_dir())
    query.add_argument("--model", default="", help="override the model ID recorded in the index")
    query.add_argument("--limit", type=int, default=5)
    query.set_defaults(func=cmd_query)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
