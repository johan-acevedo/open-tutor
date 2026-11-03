#!/usr/bin/env python3
"""Check that the review package's local links and image assets resolve."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def local_target(source: Path, value: str) -> Path | None:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    target = (source.parent / unquote(parsed.path)).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError(f"Link leaves repository: {source.relative_to(ROOT)} -> {value}")
    if not target.is_file():
        raise ValueError(f"Broken link: {source.relative_to(ROOT)} -> {value}")
    return target


class DeckParser(HTMLParser):
    def __init__(self, source: Path) -> None:
        super().__init__()
        self.source = source
        self.slides = 0
        self.images = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "section" and "slide" in (values.get("class") or "").split():
            self.slides += 1
        for attribute in ("href", "src"):
            if values.get(attribute):
                local_target(self.source, values[attribute])
        if tag == "img":
            if not values.get("alt"):
                raise ValueError("Presentation image missing alternative text")
            self.images += 1


def main() -> None:
    documents = [ROOT / name for name in (
        "README.md", "PRD.md", "BUILD-PLAN.md", "docs/technical-evidence.md",
        "design/STYLE-GUIDE.md", "design/mockups/README.md",
        "design/mockups/pass-2/README.md", "review/README.md", "review/MEETING-NOTES.md",
    )]
    for document in documents:
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", document.read_text()):
            local_target(document, target)
    deck = ROOT / "review/board-meeting.html"
    parser = DeckParser(deck)
    parser.feed(deck.read_text())
    if parser.slides != 12 or parser.images != 3:
        raise ValueError(f"Expected 12 slides and 3 mockup images, found {parser.slides} and {parser.images}")
    gallery = ROOT / "design/mockups/pass-2"
    selected = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", (gallery / "README.md").read_text())
    if len(selected) != 11:
        raise ValueError("Expected ten selected screens and one character sheet")
    for name in selected:
        raw = (gallery / name).read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Invalid PNG: {name}")
        width, height = struct.unpack(">II", raw[16:24])
        if width < 1000 or height < 600:
            raise ValueError(f"Image too small for review: {name}")
    prompts = json.loads((gallery / "prompts.json").read_text())
    for item in [prompts["character"], *prompts["screens"], *prompts["corrections"]]:
        if not item["prompt"]:
            raise ValueError("Missing generation prompt")
        for name in [item["file"], *item["references"]]:
            local_target(gallery / "prompts.json", name)
    if (ROOT / "review/board-meeting.pdf").read_bytes()[:5] != b"%PDF-":
        raise ValueError("PDF export missing or invalid")
    print("Review package checks passed: links, 12 slides, 11 selected PNGs, prompts and PDF.")


if __name__ == "__main__":
    main()
