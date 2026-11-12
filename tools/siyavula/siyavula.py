#!/usr/bin/env python3
"""Download and inspect the English CC BY EPUBs in Siyavula's catalogue."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

CATALOGUE = Path(__file__).with_name("books.json")
DEFAULT_DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "open-tutor/materials/siyavula"


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class CatalogueLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()
        self.href = ""
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.label = []

    def handle_data(self, data):
        self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            if self.href.endswith("_Eng_CC-BY.epub") and "CC-BY)" in "".join(self.label).upper():
                self.urls.add(urllib.parse.urljoin("https://www.siyavula.com", self.href))
            self.href = ""
            self.label = []


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def member_path(package, href):
    parsed = urllib.parse.urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"External EPUB resource: {href}")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(package), urllib.parse.unquote(parsed.path)))
    if path.startswith(("../", "/")):
        raise ValueError(f"EPUB resource outside archive: {href}")
    return path


def inspect_epub(path, expected_sha256=None):
    with path.open("rb") as source:
        if source.read(200).startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise ValueError("The source returned a Git LFS pointer, not an EPUB book")
    digest = sha256(path)
    if expected_sha256 and digest != expected_sha256:
        raise ValueError(f"SHA-256 mismatch for {path.name}: expected {expected_sha256}, got {digest}")
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Corrupt EPUB member: {bad}")
        if archive.read("mimetype").strip() != b"application/epub+zip":
            raise ValueError("Missing EPUB mimetype")
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfiles = container.findall(".//{*}rootfile")
        if not rootfiles:
            raise ValueError("Missing EPUB package")
        package = rootfiles[0].attrib["full-path"]
        root = ET.fromstring(archive.read(package))
        ns = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
        items = {item.attrib["id"]: item.attrib for item in root.findall("opf:manifest/opf:item", ns)}
        spine = root.findall("opf:spine/opf:itemref", ns)
        if not spine:
            raise ValueError("Empty EPUB reading order")
        chapters = []
        licenses = set()
        for entry in spine:
            item = items[entry.attrib["idref"]]
            member = member_path(package, item["href"])
            html = archive.read(member).decode("utf-8-sig")
            parser = Text()
            parser.feed(html)
            text = " ".join(" ".join(parser.parts).split())
            chapters.append({"href": member, "text_characters": len(text)})
            licenses.update(re.findall(r"https?://creativecommons\.org/licenses/[a-z-]+/[\d.]+/?", html))
        if not sum(chapter["text_characters"] for chapter in chapters):
            raise ValueError("EPUB has no readable text")
        missing = []
        for item in items.values():
            if urllib.parse.urlsplit(item["href"]).scheme:
                continue
            member = member_path(package, item["href"])
            if member not in archive.namelist():
                missing.append(member)
        return {
            "sha256": digest,
            "bytes": path.stat().st_size,
            "epub_version": root.attrib.get("version"),
            "embedded_title": root.findtext("opf:metadata/dc:title", default="", namespaces=ns),
            "embedded_language": root.findtext("opf:metadata/dc:language", default="", namespaces=ns),
            "embedded_license_links": sorted(licenses),
            "spine": chapters,
            "text_characters": sum(chapter["text_characters"] for chapter in chapters),
            "image_resources": sum(item.get("media-type", "").startswith("image/") for item in items.values()),
            "missing_manifest_resources": missing,
        }


def write_json(path, value):
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write("\n")
    temp.replace(path)


def download_book(book, data_dir):
    path = data_dir / book["filename"]
    expected = book.get("sha256")
    if path.exists():
        details = inspect_epub(path, expected)
        receipt = data_dir / (book["filename"] + ".json")
        previous = json.loads(receipt.read_text()) if receipt.exists() else {}
        result = {**previous, **book, **details, "status": "cached"}
        write_json(receipt, result)
        return result
    request = urllib.request.Request(book["url"], headers={"User-Agent": "open-tutor-materials/1.0"})
    temp = None
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            with tempfile.NamedTemporaryFile(dir=data_dir, suffix=".part", delete=False) as output:
                temp = Path(output.name)
                shutil.copyfileobj(response, output, length=1024 * 1024)
            headers = {key: response.headers.get(key) for key in ("Last-Modified", "ETag", "Content-Type")}
            final_url = response.url
        details = inspect_epub(temp, expected)
        temp.replace(path)
        result = {**book, **details, "status": "downloaded", "resolved_url": final_url, "http": headers,
                  "downloaded_at": datetime.now(timezone.utc).isoformat()}
        write_json(data_dir / (book["filename"] + ".json"), result)
        return result
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["list", "download", "verify"])
    parser.add_argument("--book", action="append", default=[], help="Select a book ID; repeat for several books")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--jobs", type=int, choices=range(1, 5), default=3, help="Concurrent downloads, 1 to 4 (default 3)")
    args = parser.parse_args(argv)
    catalog = json.loads(CATALOGUE.read_text())
    books = [book for book in catalog["books"] if not args.book or book["id"] in args.book]
    unknown = set(args.book) - {book["id"] for book in books}
    if unknown:
        parser.error(f"Unknown book IDs: {', '.join(sorted(unknown))}")
    if args.command == "list":
        print(json.dumps(books, indent=2))
        return 0
    args.data_dir.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    if args.command == "download":
        with urllib.request.urlopen(catalog["catalogue_url"], timeout=30) as response:
            snapshot = response.read()
        links = CatalogueLinks()
        links.feed(snapshot.decode())
        absent = [book["url"] for book in books if book["url"] not in links.urls]
        if absent:
            raise ValueError(f"Selected CC BY English EPUBs no longer listed: {absent}")
        (args.data_dir / "catalogue.html").write_bytes(snapshot)
    def process(book):
        if args.command == "download":
            result = download_book(book, args.data_dir)
        else:
            receipt = args.data_dir / (book["filename"] + ".json")
            previous = json.loads(receipt.read_text()) if receipt.exists() else {}
            result = {**previous, **book, **inspect_epub(args.data_dir / book["filename"], book.get("sha256")), "status": "verified"}
        if result["embedded_language"].lower() not in {"en", "en-us", "en-za", "eng"}:
            raise ValueError(f"Unexpected language: {result['embedded_language']!r}")
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(process, book): book for book in books}
        for future in as_completed(futures):
            book = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"{result['status']}: {book['id']} ({result['bytes']} bytes)", file=sys.stderr, flush=True)
            except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError, urllib.error.URLError) as error:
                errors.append({"id": book["id"], "error": str(error)})
                print(f"failed: {book['id']}: {error}", file=sys.stderr, flush=True)
    order = {book["id"]: index for index, book in enumerate(books)}
    results.sort(key=lambda result: order[result["id"]])
    report = {
        "catalogue_url": catalog["catalogue_url"],
        "catalogue_license_url": catalog["catalogue_license_url"],
        "attribution": catalog["attribution"],
        "unavailable": catalog.get("unavailable", []),
        "data_dir": str(args.data_dir.resolve()),
        "books": results,
        "errors": errors,
    }
    snapshot_path = args.data_dir / "catalogue.html"
    if snapshot_path.exists():
        report["catalogue_sha256"] = sha256(snapshot_path)
    # A subset run keeps its own report, rather than replacing the full inventory.
    report_name = "inventory.json" if not args.book else "selected-books.json"
    write_json(args.data_dir / report_name, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
