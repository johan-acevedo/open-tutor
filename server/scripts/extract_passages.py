#!/usr/bin/env python3
"""Extract original source passages from the downloaded Siyavula EPUBs.

Passage records are deterministic excerpts of the catalogue's sections: they
keep the section ID, book/version provenance, heading and breadcrumbs, readable
original prose, attached images (including math images without alt text), the
original source location, and the exact original XHTML slice. No embeddings,
no network access.

    bin/with-env uv run python scripts/extract_passages.py extract [--book ID ...]
    bin/with-env uv run python scripts/extract_passages.py extract --book mathematics-10 --out /tmp/maths10.json
    bin/with-env uv run python scripts/extract_passages.py summary
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from open_tutor.materials.catalogue import DEFAULT_BOOKS_PATH, default_data_dir
from open_tutor.materials.passages import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MIN_CHARS,
    extract_catalogue_passages,
)


def _extract(args: argparse.Namespace) -> tuple[list[dict], dict]:
    passages, meta = extract_catalogue_passages(
        data_dir=args.data_dir,
        books_path=args.books_json,
        book_ids=args.book or None,
        min_chars=args.min_chars,
        max_chars=args.max_chars,
    )
    return [passage.to_dict() for passage in passages], meta


def cmd_extract(args: argparse.Namespace) -> int:
    records, meta = _extract(args)
    payload = {"meta": meta, "passages": records}
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"out": str(args.out), "passage_count": len(records)}))
    else:
        print(text)
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    records, meta = _extract(args)
    per_book = Counter(record["book_id"] for record in records)
    per_section = Counter(record["section_id"] for record in records)
    sizes = sorted(len(record["text"]) for record in records)
    summary = {
        "meta": meta,
        "passages_per_book": dict(sorted(per_book.items())),
        "sections_with_passages": len(per_section),
        "passages_with_images": sum(1 for record in records if record["images"]),
        "passages_without_text": sum(1 for record in records if not record["text"]),
        "text_chars": {
            "min": sizes[0] if sizes else 0,
            "median": sizes[len(sizes) // 2] if sizes else 0,
            "max": sizes[-1] if sizes else 0,
        },
        "math_images": sum(
            1
            for record in records
            for image in record["images"]
            if image["kind"].startswith("math")
        ),
        "images_without_alt": sum(
            1 for record in records for image in record["images"] if not image["alt"]
        ),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, handler, help_text in (
        ("extract", cmd_extract, "write passage records as JSON"),
        ("summary", cmd_summary, "print passage counts without the records"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--book", action="append", default=[], help="book ID; repeat for several")
        command.add_argument(
            "--min-chars", type=int, default=DEFAULT_MIN_CHARS, help="close a passage at this many chars"
        )
        command.add_argument(
            "--max-chars", type=int, default=DEFAULT_MAX_CHARS, help="never add a block past this many chars"
        )
        if name == "extract":
            command.add_argument("--out", type=Path, help="write the JSON here instead of stdout")
        command.set_defaults(func=handler)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
