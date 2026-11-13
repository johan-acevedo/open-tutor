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

A full eight-book build is one explicit command with its own directory; it
never touches the proof or evaluation indexes. It embeds every extracted
passage with owned text (skipping image-only sections honestly) and reuses a
finished index when the dataset/model fingerprint is unchanged:

    bin/with-env uv run --group ml python scripts/search_materials.py build-full
    bin/with-env uv run python scripts/search_materials.py build-full  # reuse check only

Full-library pin: ``google/embeddinggemma-2`` at the cached commit
``f9972ac22e696a105c482202646979e33e4b5a1e``, fp32 CPU text-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
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
    document_input,
    load_index,
    normalize,
    query_index,
    save_index,
)

# A selector is BOOK:SUBSTRING[:CAP] against a passage's heading and breadcrumbs.
DEFAULT_SELECT_CAP = 40
DEFAULT_MAX_PASSAGES = 200

# Full eight-book library build: one explicit command, its own directory, the
# exact cached model revision. Not a default for the sample commands above.
FULL_INDEX_NAME = "full-library-index"
FULL_MODEL_REVISION = "f9972ac22e696a105c482202646979e33e4b5a1e"
FULL_BUILD_TAG = "full-library"

# Drop the original XHTML slice and block bookkeeping before embedding: search
# input is owned text plus heading/breadcrumbs only, and the slices would hold
# redundant multi-megabyte copies next to the live Passage objects.
STRIP_RECORD_KEYS = ("html", "block_range", "blocks", "container", "html_is_display_content")


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


def selector_match_count(records: list[dict], selector: dict) -> int:
    """How many passages match a selector before its cap is applied."""
    return sum(
        1
        for record in records
        if record.get("book_id") == selector["book"]
        and selector["needle"] in _haystack(record)
    )


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


def default_full_index_dir() -> Path:
    """Full-library index directory: sibling of the proof index, outside Git."""
    return default_index_dir().with_name(FULL_INDEX_NAME)


def _protected_index_dirs() -> list[Path]:
    proof = default_index_dir()
    return [proof, proof.with_name("retrieval-eval-index")]


def refuse_protected_index(path: Path) -> None:
    """Never overwrite the proof/evaluation indexes with a full-library build."""
    resolved = Path(path).expanduser().resolve()
    for protected in _protected_index_dirs():
        try:
            if resolved == protected.expanduser().resolve():
                raise ValueError(
                    f"Refusing to overwrite {protected.name}: "
                    "the full-library index needs its own directory"
                )
        except OSError:
            continue


def _available_books(books_path: Path) -> list[dict]:
    """The pinned English books from books.json (never the unavailable list)."""
    payload = json.loads(Path(books_path).read_text(encoding="utf-8"))
    books = payload.get("books") or []
    if not books:
        raise ValueError(f"No available books in {books_path}")
    return books


def full_library_fingerprint(
    book_shas: dict[str, str],
    min_chars: int,
    max_chars: int,
    passage_ids: list[str],
    model_id: str,
    model_revision: str,
    embedded_inputs: list[str],
) -> str:
    """Stable identity of one full-corpus build: source SHAs plus passage IDs."""
    canonical = json.dumps(
        {
            "books": {key: book_shas[key] for key in sorted(book_shas)},
            "min_chars": min_chars,
            "max_chars": max_chars,
            "passage_ids": list(passage_ids),
            "model_id": model_id,
            "model_revision": model_revision,
            "dtype": "torch.float32",
            "embedded_input_sha256": hashlib.sha256(json.dumps(embedded_inputs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_full_vectors(index) -> None:
    """Finite, correctly shaped vectors: dimension/count plus no NaN/Inf."""
    expected = len(index.entries) * index.dimension
    if len(index.vectors) != expected:
        raise ValueError(
            f"Vector file holds {len(index.vectors)} values, expected {expected}"
        )
    if index.dimension <= 0:
        raise ValueError(f"Invalid dimension {index.dimension}")
    if index.dtype != "torch.float32":
        raise ValueError("Full-library index must use torch.float32")
    for position in range(len(index.entries)):
        norm_squared = sum(value * value for value in index.vector(position))
        if not math.isfinite(norm_squared) or not 0.99 < norm_squared < 1.01:
            raise ValueError("Full-library index requires finite unit vectors")


def _read_saved_full_library(index_dir: Path) -> dict | None:
    meta_file = Path(index_dir) / "index.json"
    if not meta_file.is_file():
        return None
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    corpus = meta.get("corpus") or {}
    info = corpus.get(FULL_BUILD_TAG)
    return info if isinstance(info, dict) else None


def cmd_prove(args: argparse.Namespace) -> int:
    """One real query and two real documents: is the model loading at all?"""
    started = time.perf_counter()
    embedder = EmbeddingGemmaEmbedder(model_id=args.model, revision=args.revision or None)
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

    embedder = EmbeddingGemmaEmbedder(model_id=args.model, revision=args.revision or None)
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


def cmd_build_full(args: argparse.Namespace) -> int:
    """Embed every extracted passage with owned text into the full-library index.

    Reuses a finished index when its recorded dataset/model fingerprint still
    matches this corpus, so a second run does not re-embed unchanged books.
    Otherwise builds into a staging sibling and publishes only a validated
    complete result; the proof/evaluation indexes are never touched.
    """
    target = Path(args.index)
    refuse_protected_index(target)
    books = _available_books(args.books_json)
    book_ids = sorted(book["id"] for book in books)
    book_shas = {book["id"]: book["sha256"] for book in books}
    min_chars, max_chars = int(args.min_chars), int(args.max_chars)

    passages, extraction_meta = extract_catalogue_passages(
        data_dir=args.data_dir,
        books_path=args.books_json,
        book_ids=book_ids,
        min_chars=min_chars,
        max_chars=max_chars,
    )
    records: list[dict] = []
    for passage in passages:
        record = passage.to_dict()
        for key in STRIP_RECORD_KEYS:
            record.pop(key, None)
        records.append(record)
    del passages  # free the live objects; only stripped dicts are embedded
    expected = full_library_fingerprint(
        book_shas, min_chars, max_chars, [record["id"] for record in records],
        args.model, args.revision, [document_input(record) for record in records],
    )
    # Idempotent reuse: the exact same corpus and model needs no new vectors.
    # This check is stdlib-only, so a reuse run never loads torch or the model.
    if not args.force and target.is_dir():
        saved = _read_saved_full_library(target)
        if saved and saved.get("fingerprint") == expected:
            try:
                existing = load_index(target)
                _validate_full_vectors(existing)
            except (OSError, ValueError, RuntimeError, KeyError):
                pass  # fall through to a fresh staged build
            else:
                if (
                    existing.model_id == args.model
                    and existing.dtype == "torch.float32"
                    and existing.model_revision == args.revision
                    and (saved.get("book_shas") or {}) == book_shas
                    and len(existing.entries) + existing.skipped_empty_text == len(records)
                ):
                    books_covered = sorted({e.get("book_id", "") for e in existing.entries})
                    print(json.dumps({
                        "index": str(target),
                        "reused": True,
                        "fingerprint": expected,
                        "model_id": existing.model_id,
                        "model_revision": existing.model_revision,
                        "dtype": existing.dtype,
                        "vectors": len(existing.entries),
                        "dimension": existing.dimension,
                        "skipped_empty_text": existing.skipped_empty_text,
                        "books": books_covered,
                    }, indent=2, ensure_ascii=False))
                    return 0

    embedder = EmbeddingGemmaEmbedder(
        model_id=args.model, revision=args.revision or None, batch_size=args.batch_size,
    )
    if embedder.model_revision != args.revision:
        raise RuntimeError(
            f"Requested {args.model}@{args.revision}, resolved snapshot is "
            f"{embedder.model_revision!r}; refusing an unpinned full build"
        )
    corpus = {
        FULL_BUILD_TAG: {
            "fingerprint": expected,
            "books": book_ids,
            "book_shas": book_shas,
            "min_chars": min_chars,
            "max_chars": max_chars,
            "extraction_passages": len(records),
            "extraction": extraction_meta,
        },
    }
    index = build_index(records, embedder, corpus=corpus)
    _validate_full_vectors(index)
    if len(index.entries) + index.skipped_empty_text != len(records):
        raise ValueError("Built index does not cover the extracted passages")
    recorded = set(book_shas)
    covered = {entry.get("book_id", "") for entry in index.entries}
    if not recorded.issubset(covered | {""}) and covered != recorded:
        # Every book must contribute at least one embedded passage; an empty
        # book would otherwise hide as full coverage.
        missing = sorted(recorded - covered)
        if missing:
            raise ValueError(f"Full build is missing books: {', '.join(missing)}")

    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        save_index(index, staging)
        staged = load_index(staging)  # round-trip before anything is published
        _validate_full_vectors(staged)
        if len(staged.entries) != len(index.entries):
            raise ValueError("Staged full-library index failed its round-trip check")
        if target.exists():
            backup = target.with_name(target.name + ".prev")
            if backup.exists():
                shutil.rmtree(backup)
            os.replace(target, backup)
            try:
                os.replace(staging, target)
            except OSError:
                os.replace(backup, target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    published = load_index(target)
    _validate_full_vectors(published)
    per_book: dict[str, int] = {}
    for entry in published.entries:
        per_book[entry.get("book_id", "")] = per_book.get(entry.get("book_id", ""), 0) + 1
    print(json.dumps({
        "index": str(target),
        "reused": False,
        "fingerprint": expected,
        "model": embedder.describe(),
        "vectors": len(published.entries),
        "dimension": published.dimension,
        "skipped_empty_text": published.skipped_empty_text,
        "incomplete_text_passages": sum(1 for e in published.entries if not e["text_complete"]),
        "books": sorted(per_book),
        "passages_per_book": {k: per_book[k] for k in sorted(per_book)},
        "extraction_passages": len(records),
        "sections": len({e["section_id"] for e in published.entries}),
        "note": ("skipped passages have no owned text (images only); "
                   "incomplete passages keep image references and text_complete=false"),
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    index = load_index(Path(args.index))
    model_id = args.model or index.model_id
    # Query the exact revision recorded in the index unless a caller overrides
    # both the model and revision explicitly, so cached weights cannot drift.
    revision = args.revision or (index.model_revision if model_id == index.model_id else "")
    embedder = EmbeddingGemmaEmbedder(model_id=model_id, revision=revision or None)
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
    prove.add_argument("--revision", default="", help="branch, tag, or commit hash to pin")
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
        "--revision",
        default="",
        help="branch, tag, or commit hash to pin; the resolved commit is recorded",
    )
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
    query.add_argument(
        "--revision",
        default="",
        help="override the revision; default is the exact commit recorded in the index",
    )
    query.add_argument("--limit", type=int, default=5)
    query.set_defaults(func=cmd_query)

    full = sub.add_parser(
        "build-full", help="embed all extracted passages into the full-library index"
    )
    full.add_argument("--index", type=Path, default=default_full_index_dir())
    full.add_argument("--model", default=MODEL_ID)
    full.add_argument(
        "--revision",
        default=FULL_MODEL_REVISION,
        help="pinned model commit; must resolve to itself from the local cache",
    )
    full.add_argument("--batch-size", type=int, default=8)
    full.add_argument("--min-chars", type=int, default=400)
    full.add_argument("--max-chars", type=int, default=1200)
    full.add_argument("--force", action="store_true", help="re-embed even if the fingerprint matches")
    full.add_argument("--data-dir", type=Path, default=default_data_dir())
    full.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    full.set_defaults(func=cmd_build_full)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError, KeyError, ImportError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
