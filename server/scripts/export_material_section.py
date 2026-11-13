#!/usr/bin/env python3
"""Export one original catalogue section as a standalone local package.

Renders the exact original XHTML slice of a section (descendants included,
next peer excluded) with only the EPUB members it references, plus metadata
for title/book/section/source/license and an owned-text summary for later
tutor feedback.

    bin/with-env uv run python scripts/export_material_section.py --id sec-... --out /tmp/pkg
    bin/with-env uv run python scripts/export_material_section.py --id sec-... --out /tmp/pkg --book ID ...

Deterministic: reruns against the same corpus yield identical bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from open_tutor.materials.catalogue import DEFAULT_BOOKS_PATH, default_data_dir
from open_tutor.materials.render import SectionResolver, export_package, validate_package


def cmd_export(args: argparse.Namespace) -> int:
    try:
        resolver = SectionResolver(
            data_dir=args.data_dir, books_path=args.books_json, book_ids=args.book or None
        )
        metadata = export_package(resolver, args.id, args.out)
    except (OSError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    errors = validate_package(args.out, metadata)
    metadata["validation_errors"] = errors
    print(json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True))
    if errors:
        print(json.dumps({"error": "; ".join(errors)}), file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="stable catalogue section ID")
    parser.add_argument("--out", type=Path, required=True, help="package directory to write")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    parser.add_argument("--book", action="append", default=[], help="limit books; repeatable")
    parser.set_defaults(func=cmd_export)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
