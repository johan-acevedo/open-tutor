#!/usr/bin/env python3
"""Enumerate original section references from the downloaded Siyavula EPUBs.

Navigation catalogue only: stable section IDs, original XHTML locations,
titles, breadcrumbs, and source/license records. No embeddings, no text
extraction, no network access.

    bin/with-env uv run python scripts/catalogue_materials.py enumerate [--book ID ...]
    bin/with-env uv run python scripts/catalogue_materials.py get --id sec-0123456789abcdef
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from open_tutor.materials.catalogue import (
    DEFAULT_BOOKS_PATH,
    default_data_dir,
    enumerate_catalogue,
    get_by_id,
    index_sections,
)


def cmd_enumerate(args: argparse.Namespace) -> int:
    books, sections, meta = enumerate_catalogue(
        data_dir=args.data_dir, books_path=args.books_json, book_ids=args.book or None
    )
    index_sections(sections)  # fail loudly on duplicate IDs
    print(
        json.dumps(
            {
                "meta": meta,
                "books": [book.to_dict() for book in books],
                "sections": [section.to_dict() for section in sections],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    _books, sections, _meta = enumerate_catalogue(
        data_dir=args.data_dir, books_path=args.books_json, book_ids=args.book or None
    )
    try:
        section = get_by_id(sections, args.id)
    except KeyError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(section.to_dict(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    enum = sub.add_parser("enumerate", help="list section references in nav order")
    enum.add_argument("--book", action="append", default=[], help="book ID; repeat for several")
    enum.set_defaults(func=cmd_enumerate)

    get = sub.add_parser("get", help="fetch one section reference by stable ID")
    get.add_argument("--id", required=True, help="stable section ID")
    get.add_argument("--book", action="append", default=[], help="limit the search to a book ID")
    get.set_defaults(func=cmd_get)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
