"""Original-section rendering for material-library step 3a.

Turns one catalogue :class:`SectionRef` into a standalone local package: the
original XHTML slice of the section (balanced markup, descendant subsections
included, the next peer/ancestor section excluded) plus only the EPUB members
it references, with metadata for the tutor.

Display boundaries come from the original document structure, never from
passage excerpts: a section renders as its innermost ``div.section`` scope,
so child subsections render with their parent while the next peer starts a
new scope. Passage ``html``/``block_range`` spans are not display content
(they may span foreign markup); only the owned *text* and image references
are reused, as a summary for later tutor feedback.

Security posture for later embedding: no scripts are shipped, no external or
absolute resources are fetched, and event-handler attributes plus
``javascript:`` links are stripped. The only files ever written are the
package ``index.html``, ``metadata.json``, and members already present in
the pinned EPUB (the book member allowlist). Exports reject unsupported fetch vectors. HTTP serving must additionally use
a restrictive CSP and ``<iframe sandbox>``; this is a pinned-corpus exporter,
not a general sanitizer.

Standard library only: no network access, no embeddings, no storage beyond
reading the pinned EPUBs and writing the package directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import html as html_module
import json
import posixpath
import re
import zipfile
from pathlib import Path

from open_tutor.materials.catalogue import (
    DEFAULT_BOOKS_PATH,
    BookRecord,
    SectionRef,
    default_data_dir,
    enumerate_catalogue,
    index_sections,
    safe_member,
)
from open_tutor.materials.passages import extract_document_passages, parse_document

PACKAGE_SCHEMA = "open-tutor-material-section/1"

# Element names (lower-case local names) that may wrap a nav target.
SECTION_WRAPPERS = frozenset({"div", "section"})
# Resource attributes collected from the slice. Stylesheets come from the
# catalogue record (original order); images come from the slice itself.
_IMG_SRC_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE | re.DOTALL)
_STYLESHEET_HREF_RE = re.compile(
    r"""<link\b[^>]*?\brel\s*=\s*["']stylesheet["'][^>]*?\bhref\s*=\s*["']([^"']+)["']"""
    r"""|<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*?\brel\s*=\s*["']stylesheet["']""",
    re.IGNORECASE | re.DOTALL,
)
_IMG_TAG_RE = re.compile(r"""<img\b[^>]*>""", re.IGNORECASE | re.DOTALL)
# Active vectors removed by the sanitizer. Original teaching markup is kept
# verbatim otherwise.
_SCRIPT_RE = re.compile(
    r"""<script\b[^>]*/>|<script\b[^>]*>.*?</script\s*>""", re.IGNORECASE | re.DOTALL
)
_ON_ATTR_RE = re.compile(
    r"""\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE
)
_JS_HREF_RE = re.compile(
    r"""\bhref\s*=\s*(["'])\s*javascript:[^"']*["']""", re.IGNORECASE
)


class SectionResolver:
    """Catalogue loaded once, then exact section/book resolution per ID."""

    def __init__(
        self,
        data_dir: Path | None = None,
        books_path: Path = DEFAULT_BOOKS_PATH,
        book_ids: list[str] | None = None,
    ) -> None:
        directory = Path(data_dir) if data_dir is not None else default_data_dir()
        books, sections, meta = enumerate_catalogue(
            data_dir=directory, books_path=books_path, book_ids=book_ids
        )
        self.data_dir = directory
        self.books = {book.id: book for book in books}
        self.sections = index_sections(sections)
        self.meta = meta
        by_document: dict[tuple[str, str], list[SectionRef]] = {}
        for section in sections:
            by_document.setdefault((section.book_id, section.document_href), []).append(section)
        self.by_document = by_document

    def resolve(self, section_id: str) -> SectionRef:
        """Return the catalogue record for a stable section ID.

        Raises ``KeyError`` for unknown IDs (callers surface this; the ID is
        never guessed or prefix-matched).
        """
        try:
            return self.sections[section_id]
        except KeyError:
            raise KeyError(f"Unknown section ID: {section_id}") from None

    def book_for(self, section: SectionRef) -> BookRecord:
        return self.books[section.book_id]

    def epub_path_for(self, section: SectionRef) -> Path:
        return self.data_dir / self.book_for(section).filename

    def document_sections(self, section: SectionRef) -> list[SectionRef]:
        """Every nav section sharing this section's book and document."""
        return self.by_document.get((section.book_id, section.document_href), [])


def slice_starts_at_first_heading(document, heading) -> bool:
    """Whether the slice keeps its document's heading-counter context.

    The Siyavula books number chapter headings with document-scoped CSS
    counters. A slice starting at (or containing from the top) the
    document's first ``h1``/``h2`` title keeps the book's own numbers; a
    slice starting lower restarts those counters at zero, printing a
    ``"0.x"`` prefix the source book never shows.
    """
    if heading is None:
        return True
    for node in document.nodes:
        if node.order >= heading.order:
            break
        if node.tag in ("h1", "h2") and "title" in node.attrs.get("class", "").split():
            return False
    return True


def _scope_of(heading) -> object:
    """Innermost ``div.section`` scope of a nav heading, else the body."""
    node = heading
    while node is not None:
        if node.tag in SECTION_WRAPPERS and "section" in node.attrs.get("class", "").split():
            return node
        node = node.parent
    node = heading
    while node.parent is not None:
        node = node.parent
    return node


def _contains(ancestor, node) -> bool:
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def sanitize_slice(slice_html: str) -> tuple[str, list[str]]:
    """Remove active vectors from the original slice. Returns (html, notes)."""
    notes: list[str] = []
    cleaned, script_count = _SCRIPT_RE.subn("", slice_html)
    if script_count:
        notes.append(f"removed {script_count} script element(s)")
    cleaned, handler_count = _ON_ATTR_RE.subn("", cleaned)
    if handler_count:
        notes.append(f"removed {handler_count} event-handler attribute(s)")
    cleaned, js_count = _JS_HREF_RE.subn('href="#blocked"', cleaned)
    if js_count:
        notes.append(f"neutralized {js_count} javascript: link(s)")
    return cleaned, notes


def visible_scope(markup: str, *, hide_solutions: bool) -> tuple[str, list[str]]:
    """Read the shipped scope excluding the pinned corpus CSS-hidden subtrees.

    Returns the visible words and the ``src`` of every visible image in
    document order (repeats kept, one entry per ``img`` element). This handles
    the audited Siyavula selectors, not arbitrary CSS layout.
    """
    doc = parse_document(markup.encode("utf-8"))
    texts: list[str] = []
    image_sources: list[str] = []

    def walk(node, exercises=False):
        if not hasattr(node, "tag"):
            texts.append(node.data)
            return
        classes = set(node.attrs.get("class", "").split())
        if node.tag in {"script", "style", "head"} or "teachers-guide" in classes:
            return
        if hide_solutions and node.tag == "div" and "solution" in classes:
            return
        if not hide_solutions and exercises and node.tag == "h1" and "title" in classes:
            return
        if node.tag == "img":
            image_sources.append(str(node.attrs.get("src", "")))
        for child in node.content:
            walk(child, exercises or "exercises" in classes)
        if node.tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "td"}:
            texts.append("\n")

    walk(doc.root)
    return (
        "\n".join(
            " ".join(line.split())
            for line in "".join(texts).splitlines()
            if line.strip()
        ),
        image_sources,
    )


def visible_feedback(markup: str, *, hide_solutions: bool) -> tuple[str, int]:
    """Visible words plus the number of visible images (step 3a contract)."""
    text, image_sources = visible_scope(markup, hide_solutions=hide_solutions)
    return text, len(image_sources)


def assert_inert_source(markup: str) -> None:
    """Reject unsupported automatic-fetch vectors before exporting any files."""
    doc = parse_document(markup.encode("utf-8"))
    blocked = {"base", "style", "iframe", "object", "embed", "video", "audio",
               "source", "track", "use", "link", "meta", "svg", "form", "script"}
    for node in doc.nodes:
        if node.tag in blocked:
            raise ValueError(f"Unsupported active/resource element: {node.tag}")
        for key, value in node.attrs.items():
            if key.startswith("on") or key in {"srcset", "poster", "background", "srcdoc"}:
                raise ValueError(f"Unsupported active/resource attribute: {key}")
            if key == "style" and re.search(r"url\s*\(|@import|expression\s*\(", value, re.I):
                raise ValueError("Unsupported fetching inline style")
            if key == "src" and node.tag != "img":
                raise ValueError("Only packaged image src is supported")


def _image_kind(attrs_src: str, classes: str) -> str:
    class_set = set(classes.split())
    if "math-inline" in class_set:
        return "math-inline"
    if class_set & {"math-block", "math-display"}:
        return "math-block"
    if "equation/" in attrs_src:
        return "math"
    return "image"


@dataclass
class Resource:
    """One resource referenced by the slice or the stylesheet order."""

    ref: str  # original reference, verbatim
    member: str = ""  # archive member, when safely resolvable
    package_path: str = ""  # path inside the package, when copied
    kind: str = ""  # "image" or "stylesheet"
    alt: str = ""
    classes: str = ""
    resolved: bool = False
    reason: str = ""


@dataclass
class RenderedSection:
    """The original slice plus everything needed to package it."""

    section: SectionRef
    book: BookRecord
    slice_html: str  # sanitized original slice, balanced markup
    descendants: list[SectionRef] = field(default_factory=list)
    stylesheets: list[Resource] = field(default_factory=list)
    images: list[Resource] = field(default_factory=list)
    body_attributes: dict[str, str] = field(default_factory=dict)
    visible_text: str = ""
    visible_image_count: int = 0
    owned_text: str = ""
    owned_image_kinds: list[str] = field(default_factory=list)
    # The slice starts below the document's first counted heading, so
    # document-scoped book CSS counters restart at zero and would print a
    # "0.x" prefix the source book never shows. The wrapper then hides the
    # generated heading numbers instead of inventing book numbering.
    suppress_heading_numbers: bool = False
    sanitize_notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def text_complete(self) -> bool:
        return self.visible_image_count == 0


def render_section(resolver: SectionResolver, section_id: str) -> RenderedSection:
    """Render one catalogue section from its exact pinned book version.

    Raises ``KeyError`` for unknown IDs, ``FileNotFoundError`` for a missing
    EPUB, and ``ValueError`` for SHA mismatches, missing documents, or nav
    targets absent from the document.
    """
    section = resolver.resolve(section_id)
    book = resolver.book_for(section)
    epub_path = resolver.epub_path_for(section)
    if not epub_path.exists():
        raise FileNotFoundError(f"Missing EPUB for {section.book_id}: {epub_path}")
    digest = hashlib.sha256(epub_path.read_bytes()).hexdigest()
    if digest != section.book_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {epub_path.name}: catalogue pins "
            f"{section.book_sha256}, found {digest}"
        )
    with zipfile.ZipFile(epub_path) as archive:
        names = set(archive.namelist())
        try:
            raw = archive.read(section.document_href)
        except KeyError:
            raise ValueError(
                f"Document {section.document_href} missing from {epub_path.name}"
            ) from None
        document = parse_document(raw)
        doc_sections = resolver.document_sections(section)
        if section.fragment:
            heading = document.by_id.get(section.fragment)
            if heading is None:
                raise ValueError(
                    f"Nav target {section.fragment!r} not found in "
                    f"{section.document_href}"
                )
            scope = _scope_of(heading)
            descendants = [
                other
                for other in doc_sections
                if other.fragment
                and other.fragment != section.fragment
                and other.fragment in document.by_id
                and document.by_id[other.fragment].order > heading.order
                and _contains(scope, document.by_id[other.fragment])
            ]
        else:
            heading = None
            scope = next(node for node in document.nodes if node.tag == "body")
            descendants = [other for other in doc_sections if other.fragment]
        descendants.sort(key=lambda other: document.by_id[other.fragment].order)
        slice_html = raw[scope.start : scope.end].decode("utf-8")
        if scope.tag == "body":
            slice_html = slice_html[slice_html.index(">") + 1 : slice_html.rfind("</")]
        cleaned, notes = sanitize_slice(slice_html)

        doc_dir = posixpath.dirname(section.document_href)
        base = doc_dir + "/" if doc_dir else ""
        # Stylesheets keep their original hrefs verbatim (relative to the
        # document directory, which the package root mirrors) in catalogue
        # order; only archive members are copied.
        original_hrefs: list[str] = []
        for match in _STYLESHEET_HREF_RE.finditer(raw.decode("utf-8", errors="replace")):
            href = match.group(1) or match.group(2)
            if href not in original_hrefs:
                original_hrefs.append(href)
        wanted = set(section.stylesheets)
        stylesheets: list[Resource] = []
        for href in original_hrefs:
            try:
                member, _fragment = safe_member(base, href)
            except ValueError:
                stylesheets.append(
                    Resource(ref=href, kind="stylesheet",
                             reason="external, absolute, or escaping reference")
                )
                continue
            if member not in wanted:
                continue
            resource = Resource(ref=href, member=member, kind="stylesheet")
            package_rel = posixpath.relpath(member, doc_dir) if doc_dir else member
            if member in names and not package_rel.startswith("../"):
                resource.package_path = package_rel
                resource.resolved = True
            else:
                resource.reason = "stylesheet outside document directory or missing"
            stylesheets.append(resource)
        covered = {sheet.member for sheet in stylesheets if sheet.member}
        for member in section.stylesheets:
            if member not in covered:
                stylesheets.append(
                    Resource(ref=member, member=member, kind="stylesheet",
                             reason="stylesheet href not found in document")
                )

        images: list[Resource] = []
        for tag in _IMG_TAG_RE.findall(cleaned):
            src_match = re.search(r"""\bsrc\s*=\s*["']([^"']+)["']""", tag, re.IGNORECASE)
            alt_match = re.search(r"""\balt\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE)
            class_match = re.search(
                r"""\bclass\s*=\s*["']([^"']*)["']""", tag, re.IGNORECASE
            )
            if not src_match:
                continue
            ref = src_match.group(1)
            resource = Resource(
                ref=ref,
                alt=alt_match.group(1) if alt_match else "",
                classes=class_match.group(1) if class_match else "",
                kind="image",
            )
            resource.kind = _image_kind(ref, resource.classes)
            try:
                member, _fragment = safe_member(base, ref)
            except ValueError:
                resource.reason = "external, absolute, or escaping reference"
                images.append(resource)
                continue
            package_rel = posixpath.relpath(member, doc_dir) if doc_dir else member
            if member not in names:
                resource.member = member
                resource.reason = "member missing from archive"
            elif package_rel.startswith("../"):
                resource.member = member
                resource.reason = "member outside document directory"
            else:
                resource.member = member
                resource.package_path = package_rel
                resource.resolved = True
            images.append(resource)

        # Owned-source summary for later tutor feedback: exact owned text and
        # image kinds from the passage extractor (never its HTML spans).
        owned_texts: list[str] = []
        owned_kinds: list[str] = []
        for passage in extract_document_passages(raw, section.document_href, doc_sections):
            if passage.section.id != section.id:
                continue
            if passage.text:
                owned_texts.append(passage.text)
            owned_kinds.extend(image["kind"] for image in passage.images)
        warnings: list[str] = []
        for resource in stylesheets + images:
            if not resource.resolved:
                warnings.append(f"unresolved {resource.kind} {resource.ref!r}: {resource.reason}")

        visible_text, visible_images = visible_feedback(
            f"<root>{cleaned}</root>", hide_solutions=book.grade in {4, 5, 6}
        )
        return RenderedSection(
            section=section,
            suppress_heading_numbers=not slice_starts_at_first_heading(document, heading),
            book=book,
            slice_html=cleaned,
            descendants=list(descendants),
            stylesheets=stylesheets,
            images=images,
            body_attributes={key: value for node in document.nodes if node.tag == "body"
                             for key, value in node.attrs.items() if key in {"class", "lang", "dir"}},
            visible_text=visible_text,
            visible_image_count=visible_images,
            owned_text="\n\n".join(owned_texts),
            owned_image_kinds=owned_kinds,
            sanitize_notes=notes,
            warnings=warnings,
        )


def _provenance_header(rendered: RenderedSection) -> str:
    section, book = rendered.section, rendered.book
    return (
        '<header class="material-provenance"><p>'
        f'Siyavula — {html_module.escape(book.title)} — '
        f'{html_module.escape(section.heading or section.title)} — '
        f'{html_module.escape(section.license)} — siyavula.com'
        '</p></header>\n'
    )


def build_index_html(rendered: RenderedSection) -> str:
    """Standalone package page: original slice plus compact attribution.

    The slice keeps its original tags, attributes, and relative references
    verbatim (minus active vectors). Only this wrapper is new: doctype,
    language, title, viewport, stylesheet links in catalogue order, a small
    responsive safeguard for images, and a visible provenance header. The
    wrapper adds no ``<h1>`` of its own so the original heading hierarchy is
    left intact. The slice root remains a direct body child for source CSS.
    """
    section = rendered.section
    # Only resolved members are linked: an unresolvable stylesheet stays out
    # of the package rather than pointing at the archive or the network.
    links = "\n".join(
        f'    <link rel="stylesheet" type="text/css" href="{sheet.ref}"/>'
        for sheet in rendered.stylesheets
        if sheet.resolved
    )
    # Mid-document slices restart the book's document-scoped heading counters
    # at zero ("0.x"), which the source book never shows. Hide the generated
    # heading numbers; book text labels (Activity:, Revision:, ...) match
    # other selectors and are unaffected. Slices starting at the document's
    # first heading keep the book's own numbers, so no override is emitted.
    number_fix = (
        "\n      div.section > h1.title:before, "
        "div.section > h2.title:before { content: none; }"
        if rendered.suppress_heading_numbers
        else ""
    )
    body_attrs = "".join(f' {key}="{html_module.escape(value, quote=True)}"'
                         for key, value in rendered.body_attributes.items())
    title = html_module.escape(section.heading or section.title, quote=True)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="utf-8"/>\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>\n'
        f"    <title>{title}</title>\n"
        f"{links}\n"
        "    <style>\n"
        "      /* Viewer wrapper (not original content): keep wide figures usable. */\n"
        "      body img { max-width: 100%; height: auto; }\n"
        "      .material-provenance { font-family: system-ui, sans-serif; font-size: 0.9rem; }"
        f"{number_fix}\n"
        "    </style>\n"
        "  </head>\n"
        f'  <body{body_attrs} data-material-section="{section.id}">\n'
        "<!-- Safe to embed later with <iframe sandbox>: no scripts, local resources only. -->\n"
        f"{_provenance_header(rendered)}"
        f"{rendered.slice_html}\n"
        "  </body>\n"
        "</html>\n"
    )


def export_package(
    resolver: SectionResolver, section_id: str, out_dir: Path | str
) -> dict:
    """Export to a fresh empty directory; equal inputs yield identical bytes."""
    out = Path(out_dir)
    rendered = render_section(resolver, section_id)
    section, book = rendered.section, rendered.book
    epub_path = resolver.epub_path_for(section)

    assert_inert_source(f"<root>{rendered.slice_html}</root>")
    if rendered.warnings:
        raise ValueError("Unresolved package resources: " + "; ".join(rendered.warnings))
    if out.exists() and any(out.iterdir()):
        raise ValueError("Export requires a fresh empty directory per section/version")
    payloads: dict[str, bytes] = {}
    with zipfile.ZipFile(epub_path) as archive:
        for resource in rendered.stylesheets + rendered.images:
            if resource.resolved and resource.package_path not in payloads:
                data = archive.read(resource.member)
                if resource.kind == "stylesheet" and re.search(rb"url\s*\(|@import|@font-face", data, re.I):
                    raise ValueError("Unsupported CSS resource fetch: " + resource.member)
                payloads[resource.package_path] = data
    index_html = build_index_html(rendered).encode("utf-8")
    metadata = {
        "schema": PACKAGE_SCHEMA,
        "section_id": section.id,
        "title": section.heading or section.title,
        "heading": section.heading,
        "breadcrumbs": list(section.breadcrumbs),
        "book": {
            "id": book.id,
            "title": book.title,
            "filename": book.filename,
            "grade": book.grade,
            "language": section.language,
            "sha256": section.book_sha256,
        },
        "document_href": section.document_href,
        "fragment": section.fragment,
        "source_href": section.source_href,
        "source_url": section.source_url,
        "license": section.license,
        "license_url": section.license_url,
        "license_evidence": list(section.license_evidence),
        "target_found": section.target_found,
        "heading_mismatch": section.heading_mismatch,
        "descendants": [
            {
                "id": child.id,
                "title": child.heading or child.title,
                "fragment": child.fragment,
            }
            for child in rendered.descendants
        ],
        "stylesheets": [
            {
                "href": sheet.ref,
                "package_path": sheet.package_path,
                "resolved": sheet.resolved,
            }
            for sheet in rendered.stylesheets
        ],
        "owned_text": rendered.owned_text,
        "visible_text": rendered.visible_text,
        "visible_image_count": rendered.visible_image_count,
        "feedback_policy": "pinned Siyavula CSS hidden selectors excluded; scope includes descendants",
        "text_complete": rendered.text_complete,
        "images": [
            {
                "src": image.ref,
                "alt": image.alt,
                "kind": image.kind,
                "package_path": image.package_path,
                "resolved": image.resolved,
                "reason": image.reason,
            }
            for image in rendered.images
        ],
        "sanitize_notes": list(rendered.sanitize_notes),
        "warnings": list(rendered.warnings),
    }
    files = [{"path": "index.html", "bytes": len(index_html)}]
    files.extend(
        {"path": path, "bytes": len(payloads[path])} for path in sorted(payloads)
    )
    for entry in files:
        data = index_html if entry["path"] == "index.html" else payloads[entry["path"]]
        entry["sha256"] = hashlib.sha256(data).hexdigest()
    metadata["files"] = files

    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(payloads):
        target = out / Path(*Path(path).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[path])
    (out / "index.html").write_bytes(index_html)
    metadata_json = json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True)
    (out / "metadata.json").write_bytes((metadata_json + "\n").encode("utf-8"))
    return metadata


def validate_package(out_dir: Path | str, metadata: dict) -> list[str]:
    """Check an exported package: manifest integrity plus resource resolution."""
    out = Path(out_dir)
    errors: list[str] = list(metadata.get("warnings", []))
    for entry in metadata.get("files", []):
        target = out / Path(*Path(entry["path"]).parts)
        if not target.is_file():
            errors.append(f"missing file: {entry['path']}")
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
            errors.append(f"checksum mismatch: {entry['path']}")
    try:
        index = (out / "index.html").read_text(encoding="utf-8")
    except OSError as error:
        return errors + [f"index.html unreadable: {error}"]
    try:
        parse_document(index.encode("utf-8"))
    except ValueError as error:
        errors.append(f"index.html is not well-formed: {error}")
    if "<script" in index.lower():
        errors.append("index.html contains a script element")
    if _ON_ATTR_RE.search(index):
        errors.append("index.html contains an event-handler attribute")
    if "javascript:" in index.lower():
        errors.append("index.html contains a javascript: URL")
    local_refs = set(_IMG_SRC_RE.findall(index))
    local_refs.update(
        ref
        for ref in re.findall(
            r"""<link\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""", index, re.IGNORECASE
        )
        if not ref.startswith(("http://", "https://", "data:", "#"))
    )
    # Verbatim references that were never resolvable (external, escaping, or
    # missing members) stay in the markup by design and are recorded in
    # metadata warnings; only resolved resources must exist on disk.
    expected = {
        entry["src"]: entry["package_path"]
        for entry in metadata.get("images", [])
        if entry.get("resolved") and entry.get("package_path")
    }
    expected.update(
        {
            entry["href"]: entry["package_path"]
            for entry in metadata.get("stylesheets", [])
            if entry.get("resolved") and entry.get("package_path")
        }
    )
    for ref in sorted(local_refs):
        if ref not in expected:
            errors.append(f"unpackaged reference: {ref}")
            continue
        if (out / Path(*Path(expected[ref]).parts)).is_file():
            continue
        errors.append(f"unresolved local reference: {ref}")
    return errors
