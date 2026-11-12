"""Passage extraction for open-tutor material-library step 2a.

Turns the corrected catalogue :class:`SectionRef` records into deterministic
passage records that later steps can embed and cite. Section boundaries still
come only from the EPUB navigation document, as in the catalogue: document
order and the nav targets bound every excerpt, so a heading that is not a nav
target (for example "Worked example 6") stays prose inside its section and
never becomes a new section. Text of a nested nav section is never copied into
its parent, because each passage belongs to the innermost nav scope that has
already started at that point in the document.

Each passage keeps the original source location (document href, fragment,
block ordinals) and the exact original XHTML slice, so it is a reference to
the book, not a generated rewrite. Images are attached explicitly, including
``img.math-inline`` elements that carry no alt text: many expressions in the
Siyavula books exist only as images, so flattened text alone must never be
presented as a complete worked example.

Standard library only: no embeddings, no network access, no storage beyond
reading the pinned EPUB files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import posixpath
import xml.parsers.expat
import zipfile
from pathlib import Path

from open_tutor.materials.catalogue import (
    DEFAULT_BOOKS_PATH,
    SectionRef,
    default_data_dir,
    enumerate_catalogue,
    safe_member,
)

# Defaults for the embedding-sized excerpts. A passage is a run of consecutive
# blocks from one section: it closes once it holds at least ``MIN_CHARS`` of
# text, and no block is appended beyond ``MAX_CHARS``. A single block longer
# than ``MAX_CHARS`` becomes its own passage rather than being split, so every
# passage maps onto whole original elements.
DEFAULT_MIN_CHARS = 400
DEFAULT_MAX_CHARS = 1200

# Element names (lower-case local names) used to decide what a block is.
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "body",
        "caption",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hgroup",
        "hr",
        "label",
        "legend",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
# Structures kept whole: their internal markup (rows, cells) carries meaning.
ATOMIC_TAGS = frozenset({"figure", "pre", "table"})
# Never contributes readable prose or passages.
SKIP_TAGS = frozenset({"head", "nav", "script", "style", "title"})
# Class values that only mark a container as a section; not useful as context.
STRUCTURAL_CLASSES = frozenset({"section"})

MATH_INLINE_CLASSES = frozenset({"math-inline"})
MATH_BLOCK_CLASSES = frozenset({"math-block", "math-display"})


@dataclass(eq=False)
class _Text:
    """Verbatim character data, with its byte span in the original XHTML."""

    data: str
    start: int
    end: int


@dataclass(eq=False)
class _Node:
    """Minimal element node with byte offsets into the original XHTML."""

    tag: str
    attrs: dict[str, str]
    order: int
    start: int
    end: int = 0
    parent: "_Node | None" = None
    content: list["_Node | _Text"] = field(default_factory=list)


@dataclass
class _Document:
    raw: bytes
    root: _Node
    nodes: list[_Node]  # document order
    by_id: dict[str, _Node]


def _tag_end(raw: bytes, index: int) -> int:
    """End of the tag that starts at ``index`` (one past its ``>``)."""
    close = raw.find(b">", index)
    return len(raw) if close < 0 else close + 1


def parse_document(raw: bytes) -> _Document:
    """Parse one content document, keeping byte offsets for original slices."""
    parser = xml.parsers.expat.ParserCreate()
    nodes: list[_Node] = []
    stack: list[_Node] = []
    roots: list[_Node] = []

    def start(name: str, attrs: dict[str, str]) -> None:
        node = _Node(
            tag=name.rsplit(":", 1)[-1].lower(),
            attrs={key.rsplit(":", 1)[-1].lower(): value for key, value in attrs.items()},
            order=len(nodes),
            start=parser.CurrentByteIndex,
            parent=stack[-1] if stack else None,
        )
        (stack[-1].content if stack else roots).append(node)
        stack.append(node)
        nodes.append(node)

    def end(_name: str) -> None:
        node = stack.pop()
        node.end = _tag_end(raw, parser.CurrentByteIndex)

    def chars(data: str) -> None:
        if not stack or not data:
            return
        begin = parser.CurrentByteIndex
        following_tag = raw.find(b"<", begin)
        stack[-1].content.append(
            _Text(data=data, start=begin, end=len(raw) if following_tag < 0 else following_tag)
        )

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(raw, True)
    except xml.parsers.expat.ExpatError as error:
        raise ValueError(f"Content document is not well-formed XHTML: {error}") from error
    if not roots:
        raise ValueError("Content document has no root element")
    by_id: dict[str, _Node] = {}
    for node in nodes:
        ident = node.attrs.get("id")
        if ident and ident not in by_id:
            by_id[ident] = node
    return _Document(raw=raw, root=roots[0], nodes=nodes, by_id=by_id)


def _inline_prose(content: list["_Node | _Text"]) -> str:
    parts: list[str] = []
    for item in content:
        if isinstance(item, _Text):
            parts.append(item.data)
        elif item.tag in SKIP_TAGS:
            continue
        elif item.tag in {"br", "hr", "img"}:
            parts.append(" ")
        else:
            parts.append(" " + _inline_prose(item.content) + " ")
    return " ".join("".join(parts).split())


@lru_cache(maxsize=None)
def _has_block(node: _Node) -> bool:
    """Whether the element contains further block-level content."""
    for item in node.content:
        if isinstance(item, _Node) and (item.tag in BLOCK_TAGS or _has_block(item)):
            return True
    return False


def _image_kind(attrs: dict[str, str], member: str) -> str:
    classes = set(attrs.get("class", "").split())
    if classes & MATH_INLINE_CLASSES:
        return "math-inline"
    if classes & MATH_BLOCK_CLASSES:
        return "math-block"
    if "equation/" in member:
        # Equation image without a class hint (some books omit it).
        return "math"
    return "image"


def _image_src(doc_dir: str, attrs: dict[str, str]) -> str:
    src = attrs.get("src", "")
    if not src:
        return ""
    try:
        member, _fragment = safe_member(doc_dir + "/" if doc_dir else "", src)
    except ValueError:
        return src  # absolute or external reference; kept verbatim
    return member


def _images(content: list["_Node | _Text"], doc_dir: str, out: list[dict]) -> None:
    for item in content:
        if not isinstance(item, _Node) or item.tag in SKIP_TAGS:
            continue
        if item.tag == "img":
            member = _image_src(doc_dir, item.attrs)
            out.append(
                {
                    "src": member,
                    "alt": item.attrs.get("alt", ""),
                    "kind": _image_kind(item.attrs, member),
                    "block": -1,  # filled in by the caller
                }
            )
        else:
            _images(item.content, doc_dir, out)


@dataclass
class _Block:
    """One original unit of content: an element, or a run of inline content."""

    ordinal: int  # block ordinal within the document, in document order
    text: str
    images: list[dict]
    start: int
    end: int
    container: str
    # Origin of the block: its own element, or the container holding an inline run.
    node: _Node


@dataclass
class _Target:
    """One nav section anchored at an element of one document."""

    section: SectionRef
    heading_order: int  # document order of the nav target; -1 for a whole document
    scope: _Node


def _document_blocks(raw: bytes, document_href: str) -> tuple[_Document, list[_Block]]:
    """Every original content unit of one document, in document order.

    Block elements without block-level content are taken whole. Containers keep
    their own inline text as separate inline blocks, so leading text in a list
    item or problem statement is not lost and is not duplicated in its children.
    """
    document = parse_document(raw)
    doc_dir = posixpath.dirname(document_href)
    blocks: list[_Block] = []
    classes: list[str] = []

    def context() -> str:
        for classes_value in reversed(classes):
            if classes_value and classes_value not in STRUCTURAL_CLASSES:
                return classes_value
        return ""

    def emit(text: str, images: list[dict], start: int, end: int, origin: _Node) -> None:
        if not text and not images:
            return
        for image in images:
            image["block"] = len(blocks)
        blocks.append(
            _Block(
                ordinal=len(blocks),
                text=text,
                images=images,
                start=start,
                end=end,
                container=context(),
                node=origin,
            )
        )

    def emit_element(node: _Node) -> None:
        images: list[dict] = []
        _images([node], doc_dir, images)
        emit(_inline_prose([node]), images, node.start, node.end, node)

    def emit_run(run: list["_Node | _Text"], origin: _Node) -> None:
        if not run:
            return
        images: list[dict] = []
        _images(run, doc_dir, images)
        emit(_inline_prose(run), images, run[0].start, run[-1].end, origin)

    def walk(node: _Node) -> None:
        if node.tag in SKIP_TAGS:
            return
        if node.tag in ATOMIC_TAGS or not _has_block(node):
            emit_element(node)
            return
        classes.append(" ".join(node.attrs.get("class", "").split()))
        run: list[_Node | _Text] = []
        try:
            for item in node.content:
                if isinstance(item, _Text):
                    run.append(item)
                elif item.tag in SKIP_TAGS:
                    emit_run(run, node)
                    run = []
                elif item.tag in BLOCK_TAGS or item.tag in ATOMIC_TAGS or _has_block(item):
                    emit_run(run, node)
                    run = []
                    walk(item)
                else:
                    run.append(item)  # inline element stays with its text
            emit_run(run, node)
        finally:
            classes.pop()

    walk(_body(document))
    return document, blocks


def _body(document: _Document) -> _Node:
    for node in document.nodes:
        if node.tag == "body":
            return node
    raise ValueError("Content document has no body element")


def _scope_of(heading: _Node) -> _Node:
    """The innermost enclosing ``div.section`` of a nav target, else the body."""
    node: _Node | None = heading
    while node is not None:
        if node.tag in {"div", "section"} and "section" in node.attrs.get("class", "").split():
            return node
        node = node.parent
    node = heading
    while node.parent is not None:
        node = node.parent
    return node


def _targets(document: _Document, sections: list[SectionRef]) -> list[_Target]:
    """Nav targets of one document, in document order."""
    targets: list[_Target] = []
    for section in sections:
        if not section.fragment:
            # Catalogue section covering a whole document (for example frontmatter).
            targets.append(_Target(section=section, heading_order=-1, scope=_body(document)))
            continue
        heading = document.by_id.get(section.fragment)
        if heading is None:
            raise ValueError(f"Nav target {section.fragment!r} not found in {section.document_href}")
        targets.append(
            _Target(section=section, heading_order=heading.order, scope=_scope_of(heading))
        )
    targets.sort(key=lambda target: target.heading_order)
    return targets


def _owner(block: _Block, targets: list[_Target]) -> _Target:
    """Innermost nav target that has already started at this block."""
    order = block.node.order
    node: _Node | None = block.node
    while node is not None:
        candidates = [
            target for target in targets if target.scope is node and target.heading_order < order
        ]
        if candidates:
            return candidates[-1]  # deepest scope wins; later target wins inside it
        node = node.parent
    return targets[0]  # content before the first nav target belongs to it


def passage_id(section: SectionRef, first: int, last: int, text: str) -> str:
    """Stable passage ID from the book version, source span, and text."""
    key = "|".join(
        (
            section.book_sha256,
            section.document_href,
            section.fragment,
            str(first),
            str(last),
            hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        )
    )
    return "psg-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass
class Passage:
    """One embeddable excerpt of one original book section."""

    id: str
    section: SectionRef
    ordinal: int  # 1-based position within the section
    blocks: list[_Block]
    text: str
    html: str
    images: list[dict]
    container: str

    @property
    def text_complete(self) -> bool:
        """False when the passage has images, so text alone is not the content."""
        return not self.images

    def to_dict(self) -> dict:
        section = self.section
        return {
            "id": self.id,
            "ordinal": self.ordinal,
            "section_id": section.id,
            "book_id": section.book_id,
            "book_sha256": section.book_sha256,
            "grade": section.grade,
            "language": section.language,
            "source_url": section.source_url,
            "license": section.license,
            "license_url": section.license_url,
            "heading": section.title,
            "breadcrumbs": list(section.breadcrumbs),
            "document_href": section.document_href,
            "fragment": section.fragment,
            "source_href": section.source_href,
            "block_range": [self.blocks[0].ordinal, self.blocks[-1].ordinal],
            "container": self.container,
            "text": self.text,
            "text_complete": self.text_complete,
            "images": [dict(image) for image in self.images],
            "html": self.html,
        }


def _chunks(blocks: list[_Block], min_chars: int, max_chars: int) -> list[list[_Block]]:
    """Greedy consecutive runs of blocks sized for embedding."""
    if min_chars <= 0 or max_chars < min_chars:
        raise ValueError("Passage sizes need 0 < min_chars <= max_chars")
    chunks: list[list[_Block]] = []
    current: list[_Block] = []
    size = 0
    for block in blocks:
        if current and size + len(block.text) > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(block)
        size += len(block.text)
        if size >= min_chars:
            chunks.append(current)
            current, size = [], 0
    if current:
        chunks.append(current)
    return chunks


def _passage(section: SectionRef, raw: bytes, ordinal: int, blocks: list[_Block]) -> Passage:
    text = "\n\n".join(block.text for block in blocks if block.text)
    first, last = blocks[0], blocks[-1]
    images = [image for block in blocks for image in block.images]
    return Passage(
        id=passage_id(section, first.ordinal, last.ordinal, text),
        section=section,
        ordinal=ordinal,
        blocks=blocks,
        text=text,
        html=raw[first.start : last.end].decode("utf-8"),
        images=images,
        container=first.container,
    )


def extract_document_passages(
    raw: bytes,
    document_href: str,
    sections: list[SectionRef],
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[Passage]:
    """Extract the passages of every nav section that lives in one document."""
    if not sections:
        raise ValueError(f"No nav sections for {document_href}")
    document, blocks = _document_blocks(raw, document_href)
    targets = _targets(document, sections)
    headings = {id(document.by_id[target.section.fragment]) for target in targets if target.section.fragment}

    grouped: dict[int, list[_Block]] = {id(target.section): [] for target in targets}
    for block in blocks:
        if id(block.node) in headings:
            continue  # the section heading is the record's heading, not body prose
        grouped[id(_owner(block, targets).section)].append(block)

    passages: list[Passage] = []
    for target in targets:
        chunked = _chunks(grouped[id(target.section)], min_chars, max_chars)
        for ordinal, chunk in enumerate(chunked, start=1):
            passages.append(_passage(target.section, raw, ordinal, chunk))
    return passages


def extract_book_passages(
    epub_path: Path,
    sections: list[SectionRef],
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[Passage]:
    """Extract passages for one book, reading each content document once."""
    by_document: dict[str, list[SectionRef]] = {}
    for section in sections:
        by_document.setdefault(section.document_href, []).append(section)
    passages: list[Passage] = []
    with zipfile.ZipFile(epub_path) as archive:
        for document_href, document_sections in by_document.items():
            raw = archive.read(document_href)
            passages.extend(
                extract_document_passages(
                    raw, document_href, document_sections, min_chars=min_chars, max_chars=max_chars
                )
            )
    return passages


def extract_catalogue_passages(
    data_dir: Path | None = None,
    books_path: Path = DEFAULT_BOOKS_PATH,
    book_ids: list[str] | None = None,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> tuple[list[Passage], dict]:
    """Extract passages for the pinned books present in ``data_dir``.

    Returns ``(passages, meta)``. Passages follow the catalogue's nav order and
    are stable between runs on the same corpus.
    """
    directory = Path(data_dir) if data_dir is not None else default_data_dir()
    books, sections, catalogue_meta = enumerate_catalogue(
        data_dir=directory, books_path=books_path, book_ids=book_ids
    )
    by_book: dict[str, list[SectionRef]] = {}
    for section in sections:
        by_book.setdefault(section.book_id, []).append(section)
    passages: list[Passage] = []
    for book in books:
        passages.extend(
            extract_book_passages(
                directory / book.filename,
                by_book.get(book.id, []),
                min_chars=min_chars,
                max_chars=max_chars,
            )
        )
    meta = {
        **catalogue_meta,
        "min_chars": min_chars,
        "max_chars": max_chars,
        "book_count": len(books),
        "section_count": len(sections),
        "passage_count": len(passages),
    }
    return passages, meta
