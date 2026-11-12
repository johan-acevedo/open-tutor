"""Source catalogue for open-tutor material-library step 1.

Builds stable, deterministic section references from the original English
Siyavula EPUBs. The EPUB navigation document (``properties="nav"``) is
authoritative for section boundaries: every ``<a>`` in the nav becomes one
section record, with breadcrumbs taken from the nav nesting. Headings inside
the content documents are *not* used, because worked examples use nested
headings that do not mark section boundaries, and not every heading has an ID.

Each record keeps the original archive locations (document href, fragment,
stylesheets) so later steps can serve the exact original section with its
images and styles. No text is extracted here: many mathematical expressions
are images without alt text, so flattened text would be an incomplete and
misleading source.

This module uses only the standard library. It performs no network access,
no embeddings, and no storage beyond reading the EPUB files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import posixpath
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

XHTML_NS = "http://www.w3.org/1999/xhtml"
OPF_NS = "http://www.idpf.org/2007/opf"
OPS_NS = "http://www.idpf.org/2007/ops"

# Repo root is three levels above this file: materials/ -> open_tutor/ -> server/ -> root.
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BOOKS_PATH = REPO_ROOT / "tools" / "siyavula" / "books.json"


def default_data_dir() -> Path:
    """Corpus directory, honouring XDG like tools/siyavula/siyavula.py."""
    import os

    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / "open-tutor" / "materials" / "siyavula"


def section_id(book_sha256: str, document_href: str, fragment: str) -> str:
    """Stable section ID derived from the book SHA-256 plus the original href/fragment."""
    key = f"{book_sha256}|{document_href}|{fragment or ''}"
    return "sec-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def safe_member(base_dir: str, href: str) -> tuple[str, str]:
    """Resolve a same-document nav href against a base directory inside the archive.

    Returns ``(member_path, fragment)``. Rejects absolute URLs, absolute
    paths, and paths escaping the archive, so a hostile EPUB cannot make the
    reader open files outside the book.
    """
    parsed = urllib.parse.urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"External EPUB resource: {href!r}")
    if not parsed.path:
        raise ValueError(f"EPUB nav link without a document path: {href!r}")
    path = posixpath.normpath(posixpath.join(base_dir, urllib.parse.unquote(parsed.path)))
    if path.startswith(("../", "/")) or path == "..":
        raise ValueError(f"EPUB resource outside archive: {href!r}")
    return path, parsed.fragment


def _norm_text(text: str) -> str:
    return " ".join(text.split())


@dataclass
class SectionRef:
    """One navigable section of one source book."""

    id: str
    book_id: str
    title: str
    breadcrumbs: list[str] = field(default_factory=list)
    # Original locations inside the EPUB archive (never rewritten).
    document_href: str = ""
    fragment: str = ""
    source_href: str = ""
    stylesheets: list[str] = field(default_factory=list)
    # Source and license provenance.
    grade: int | None = None
    language: str = ""
    source_url: str = ""
    license: str = ""
    license_url: str = ""
    license_evidence: list[str] = field(default_factory=list)
    book_sha256: str = ""
    # Whether the fragment target id was found in the content document.
    target_found: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "book_id": self.book_id,
            "title": self.title,
            "breadcrumbs": list(self.breadcrumbs),
            "document_href": self.document_href,
            "fragment": self.fragment,
            "source_href": self.source_href,
            "stylesheets": list(self.stylesheets),
            "grade": self.grade,
            "language": self.language,
            "source_url": self.source_url,
            "license": self.license,
            "license_url": self.license_url,
            "license_evidence": list(self.license_evidence),
            "book_sha256": self.book_sha256,
            "target_found": self.target_found,
        }


@dataclass
class BookRecord:
    """Catalogue-level record for one source book."""

    id: str
    title: str
    filename: str
    sha256: str
    grade: int | None
    language: str
    source_url: str
    license: str
    license_url: str
    license_evidence: list[str] = field(default_factory=list)
    section_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "filename": self.filename,
            "sha256": self.sha256,
            "grade": self.grade,
            "language": self.language,
            "source_url": self.source_url,
            "license": self.license,
            "license_url": self.license_url,
            "license_evidence": list(self.license_evidence),
            "section_count": self.section_count,
        }


def load_books(books_path: Path = DEFAULT_BOOKS_PATH) -> tuple[dict, list[dict]]:
    """Load the pinned source catalogue (books.json)."""
    catalog = json.loads(Path(books_path).read_text(encoding="utf-8"))
    return catalog, list(catalog["books"])


def _read_receipt_licenses(data_dir: Path, filename: str) -> list[str]:
    """Embedded license links recorded by the download inspector, if present."""
    receipt = data_dir / (filename + ".json")
    if not receipt.exists():
        return []
    try:
        details = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    links = details.get("embedded_license_links") or []
    return sorted({str(link) for link in links})


def _find_nav(archive: zipfile.ZipFile, package_path: str, root: ET.Element) -> str:
    """Locate the EPUB 3 navigation document via the manifest ``nav`` property."""
    ns = {"opf": OPF_NS}
    package_dir = posixpath.dirname(package_path)
    for item in root.findall("opf:manifest/opf:item", ns):
        props = item.attrib.get("properties", "").split()
        if "nav" in props:
            member, _ = safe_member(package_dir + "/" if package_dir else "", item.attrib["href"])
            if member not in archive.namelist():
                raise ValueError(f"EPUB nav document missing from archive: {member}")
            return member
    raise ValueError("EPUB has no navigation document (manifest 'nav' property)")


def _walk_nav_list(
    ol: ET.Element, x: str, trail: list[str], out: list[tuple[str, list[str], str]]
) -> None:
    """Flatten one nav ``<ol>`` into ``(href, breadcrumbs, title)`` in document order."""
    for li in ol.findall(f"{x}li"):
        link = li.find(f"{x}a")
        nested = li.find(f"{x}ol")
        title = _norm_text("".join(link.itertext())) if link is not None else ""
        href = link.attrib.get("href", "") if link is not None else ""
        if link is not None and href:
            out.append((href, list(trail), title))
        if nested is not None:
            _walk_nav_list(nested, x, trail + ([title] if title else []), out)


_ID_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")
_STYLESHEET_RE = re.compile(
    r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*\bhref\s*=\s*["']([^"']+)["']"""
    r"""|<link\b[^>]*\bhref\s*=\s*["']([^"']+)["'][^>]*\brel\s*=\s*["']stylesheet["']""",
    re.IGNORECASE,
)


def _document_ids(html: str) -> set[str]:
    return set(_ID_RE.findall(html))


def _document_stylesheets(html: str, doc_dir: str, names: set[str]) -> list[str]:
    found: list[str] = []
    for match in _STYLESHEET_RE.finditer(html):
        href = match.group(1) or match.group(2)
        try:
            member, _ = safe_member(doc_dir + "/" if doc_dir else "", href)
        except ValueError:
            continue
        if member in names and member not in found:
            found.append(member)
    return sorted(found)


def enumerate_book(
    epub_path: Path,
    book: dict,
    license_evidence: list[str] | None = None,
) -> tuple[BookRecord, list[SectionRef]]:
    """Enumerate the nav sections of one EPUB. Deterministic in nav order."""
    book_id = book["id"]
    expected_sha = book.get("sha256")
    digest = hashlib.sha256(Path(epub_path).read_bytes()).hexdigest()
    if expected_sha and digest != expected_sha:
        raise ValueError(f"SHA-256 mismatch for {epub_path.name}: expected {expected_sha}, got {digest}")

    with zipfile.ZipFile(epub_path) as archive:
        names = set(archive.namelist())
        container = ET.fromstring(archive.read("META-INF/container.xml"))
        rootfiles = container.findall(".//{*}rootfile")
        if not rootfiles:
            raise ValueError(f"Missing EPUB package in {epub_path.name}")
        package_path = rootfiles[0].attrib["full-path"]
        package_root = ET.fromstring(archive.read(package_path))
        nav_member = _find_nav(archive, package_path, package_root)
        nav_dir = posixpath.dirname(nav_member)
        nav_prefix = nav_dir + "/" if nav_dir else ""

        nav_root = ET.fromstring(archive.read(nav_member))
        x = f"{{{XHTML_NS}}}"
        toc_nav = None
        for candidate in nav_root.iter(f"{x}nav"):
            nav_type = candidate.attrib.get(f"{{{OPS_NS}}}type", "")
            if "toc" in nav_type.split() or candidate.attrib.get("id") == "toc":
                toc_nav = candidate
                break
        if toc_nav is None:
            raise ValueError(f"EPUB nav has no toc navigation element in {epub_path.name}")
        top = toc_nav.find(f"{x}ol")
        if top is None:
            raise ValueError(f"EPUB toc nav has no list in {epub_path.name}")
        raw_links: list[tuple[str, list[str], str]] = []
        _walk_nav_list(top, x, [], raw_links)

        # Read each referenced content document once.
        doc_ids: dict[str, set[str]] = {}
        doc_styles: dict[str, list[str]] = {}
        for href, _trail, _label in raw_links:
            member, _frag = safe_member(nav_prefix, href)
            if member not in names:
                raise ValueError(f"EPUB nav target missing from archive: {href!r} in {epub_path.name}")
            if member not in doc_ids:
                html = archive.read(member).decode("utf-8-sig")
                doc_ids[member] = _document_ids(html)
                doc_styles[member] = _document_stylesheets(html, posixpath.dirname(member), names)

        sections: list[SectionRef] = []
        for href, trail, label in raw_links:
            member, frag = safe_member(nav_prefix, href)
            sections.append(
                SectionRef(
                    id=section_id(digest, member, frag),
                    book_id=book_id,
                    title=label,
                    breadcrumbs=trail,
                    document_href=member,
                    fragment=frag,
                    source_href=href,
                    stylesheets=doc_styles[member],
                    grade=book.get("grade"),
                    language=book.get("language", ""),
                    source_url=book.get("url", ""),
                    license=book.get("license", ""),
                    license_url="",
                    license_evidence=list(license_evidence or []),
                    book_sha256=digest,
                    target_found=(not frag) or (frag in doc_ids[member]),
                )
            )

    record = BookRecord(
        id=book_id,
        title=book.get("title", ""),
        filename=Path(epub_path).name,
        sha256=digest,
        grade=book.get("grade"),
        language=book.get("language", ""),
        source_url=book.get("url", ""),
        license=book.get("license", ""),
        license_url="",
        license_evidence=list(license_evidence or []),
        section_count=len(sections),
    )
    return record, sections


def enumerate_catalogue(
    data_dir: Path = None,  # type: ignore[assignment]
    books_path: Path = DEFAULT_BOOKS_PATH,
    book_ids: list[str] | None = None,
) -> tuple[list[BookRecord], list[SectionRef], dict]:
    """Enumerate sections for the pinned books present in ``data_dir``.

    Returns ``(books, sections, catalog_meta)`` where ``catalog_meta`` carries
    the catalogue-level license and attribution. Raises ``ValueError`` for
    unknown book IDs and ``FileNotFoundError`` for missing EPUB files, so a
    partial corpus fails loudly instead of silently.
    """
    data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
    catalog, books = load_books(books_path)
    if book_ids:
        wanted = set(book_ids)
        unknown = wanted - {book["id"] for book in books}
        if unknown:
            raise ValueError(f"Unknown book IDs: {', '.join(sorted(unknown))}")
        books = [book for book in books if book["id"] in wanted]
    meta = {
        "catalogue_url": catalog.get("catalogue_url", ""),
        "catalogue_license_url": catalog.get("catalogue_license_url", ""),
        "attribution": catalog.get("attribution", ""),
    }
    records: list[BookRecord] = []
    sections: list[SectionRef] = []
    for book in books:
        epub_path = data_dir / book["filename"]
        if not epub_path.exists():
            raise FileNotFoundError(f"Missing EPUB for {book['id']}: {epub_path}")
        evidence = _read_receipt_licenses(data_dir, book["filename"])
        record, book_sections = enumerate_book(epub_path, book, evidence)
        record.license_url = meta["catalogue_license_url"]
        for section in book_sections:
            section.license_url = meta["catalogue_license_url"]
        records.append(record)
        sections.extend(book_sections)
    # Deterministic reruns: nav order is already stable; keep it.
    return records, sections, meta


def index_sections(sections: list[SectionRef]) -> dict[str, SectionRef]:
    """Map section IDs to records, failing loudly on duplicates."""
    index: dict[str, SectionRef] = {}
    for section in sections:
        if section.id in index:
            raise ValueError(f"Duplicate section ID: {section.id}")
        index[section.id] = section
    return index


def get_by_id(sections: list[SectionRef], section_id_value: str) -> SectionRef:
    """Return the section with the given stable ID, or raise ``KeyError``."""
    for section in sections:
        if section.id == section_id_value:
            return section
    raise KeyError(f"Unknown section ID: {section_id_value}")
