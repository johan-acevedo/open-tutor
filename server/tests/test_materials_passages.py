"""Behavioural tests for source passage extraction (step 2a).

Synthetic-EPUB tests pin the extraction rules (nav scopes, inline text, images,
original slices). Live-corpus tests read the real downloaded EPUBs and skip when
the corpus is absent.
"""

import json
from pathlib import Path
import zipfile

import pytest

from open_tutor.materials.catalogue import enumerate_book, index_sections
from open_tutor.materials.passages import (
    Passage,
    extract_book_passages,
    extract_catalogue_passages,
    extract_document_passages,
)

CORPUS = Path.home() / ".local" / "share" / "open-tutor" / "materials" / "siyavula"
BOOKS_JSON = Path(__file__).resolve().parents[2] / "tools" / "siyavula" / "books.json"
GRADE6_EPUB = "Gr6_NaturalSciences_Learner_Eng_CC-BY.epub"
MATHS10_EPUB = "Gr10_Mathematics_Learner_Eng_CC-BY.epub"

needs_corpus = pytest.mark.skipif(
    not (CORPUS / GRADE6_EPUB).exists() or not (CORPUS / MATHS10_EPUB).exists(),
    reason="downloaded Siyavula corpus is not present",
)


def write_epub(path: Path, nav_items: str, docs: dict[str, str]) -> Path:
    """Write a minimal EPUB 3 with a manifest nav and XHTML content documents."""
    manifest = "".join(
        f'<item id="d{index}" href="text/{name}" media-type="application/xhtml+xml"/>'
        for index, name in enumerate(docs)
    )
    package = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>t</dc:title></metadata>'
        f'<manifest><item id="nav" href="text/nav.xhtml" '
        f'media-type="application/xhtml+xml" properties="nav"/>{manifest}</manifest>'
        '<spine><itemref idref="d0"/></spine></package>'
    )
    nav = (
        '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>n</title></head>'
        f'<body><nav epub:type="toc" id="toc"><ol>{nav_items}</ol></nav></body></html>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="pkg.opf"/></rootfiles></container>',
        )
        archive.writestr("pkg.opf", package)
        archive.writestr("text/nav.xhtml", nav)
        for name, body in docs.items():
            archive.writestr(f"text/{name}", body)
    return path


def book(**overrides) -> dict:
    record = {
        "id": "tiny-book",
        "title": "Tiny",
        "filename": "tiny.epub",
        "grade": 6,
        "language": "en",
        "url": "https://www.siyavula.com/read",
        "license": "CC-BY",
    }
    record.update(overrides)
    return record


def doc(body: str) -> str:
    return f'<html xmlns="http://www.w3.org/1999/xhtml"><body>{body}</body></html>'


NESTED_NAV = (
    '<li><a href="ch.xhtml#top">Top</a><ol>'
    '<li><a href="ch.xhtml#sub">Sub</a></li></ol></li>'
)
NESTED_DOC = doc(
    '<div class="section"><h2 id="top">Top</h2><p>Parent intro.</p>'
    '<div class="section"><h3 id="sub">Sub</h3><p>Child body text.</p></div>'
    '<p>Parent tail.</p></div>'
)


def sections_of(tmp_path: Path, nav_items: str, docs: dict[str, str]):
    epub = write_epub(tmp_path / "tiny.epub", nav_items, docs)
    _record, sections = enumerate_book(epub, book())
    return epub, sections


def passages_of(tmp_path: Path, nav_items: str, docs: dict[str, str], **kwargs) -> list[Passage]:
    epub, sections = sections_of(tmp_path, nav_items, docs)
    with zipfile.ZipFile(epub) as archive:
        raw = archive.read(sections[0].document_href)
    return extract_document_passages(raw, sections[0].document_href, sections, **kwargs)


def test_nested_sections_keep_their_own_text_and_nav_order(tmp_path):
    passages = passages_of(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC}, min_chars=1)
    parent = [p for p in passages if p.section.title == "Top"]
    child = [p for p in passages if p.section.title == "Sub"]
    parent_text = " ".join(p.text for p in parent)
    child_text = " ".join(p.text for p in child)
    assert "Parent intro." in parent_text and "Parent tail." in parent_text
    assert "Child body text." not in parent_text
    assert "Child body text." in child_text
    assert "Parent intro." not in child_text
    parent_blocks = {b.ordinal for p in parent for b in p.blocks}
    child_blocks = {b.ordinal for p in child for b in p.blocks}
    assert not parent_blocks & child_blocks  # no block is extracted twice
    assert [p.ordinal for p in parent] == list(range(1, len(parent) + 1))


def test_non_nav_heading_is_prose_not_a_section(tmp_path):
    body = doc(
        '<div class="section"><h2 id="a">A</h2><p>Intro text here.</p>'
        '<div class="worked_example"><h1 class="title">Worked example 1: Do it</h1>'
        '<p>Step one sentence.</p></div></div>'
    )
    epub, sections = sections_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body})
    assert [section.title for section in sections] == ["A"]
    passages = extract_book_passages(epub, sections, min_chars=1)
    text = " ".join(p.text for p in passages)
    assert "Worked example 1: Do it" in text and "Step one sentence." in text
    assert {p.section.id for p in passages} == {sections[0].id}


def test_math_images_without_alt_are_attached_and_text_is_marked_incomplete(tmp_path):
    body = doc(
        '<div class="section"><h2 id="a">A</h2>'
        '<p>Solve <img class="math-inline" src="equation/abc.png"/> for the value.</p>'
        '<img class="math-block" src="equation/def.png"/></div>'
    )
    passages = passages_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body})
    passage = passages[0]
    assert passage.text == "Solve for the value."
    assert [image["src"] for image in passage.images] == [
        "text/equation/abc.png",
        "text/equation/def.png",
    ]
    assert [image["kind"] for image in passage.images] == ["math-inline", "math-block"]
    assert [image["alt"] for image in passage.images] == ["", ""]
    assert passage.text_complete is False
    record = passage.to_dict()
    assert record["text_complete"] is False
    # The image belongs to the paragraph that carries it, not to the heading block.
    assert record["images"][0]["block"] == passage.blocks[0].ordinal
    assert record["block_range"] == [passage.blocks[0].ordinal, passage.blocks[-1].ordinal]


def test_leading_text_of_a_problem_is_kept(tmp_path):
    body = doc(
        '<div class="section"><h2 id="a">A</h2>'
        '<div class="problem">Why is this unsafe?<p>Because it is broken.</p></div></div>'
    )
    passages = passages_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body})
    text = " ".join(p.text for p in passages)
    assert "Why is this unsafe?" in text
    assert "Because it is broken." in text
    assert text.count("Why is this unsafe?") == 1


def test_html_is_the_original_slice_and_provenance_is_complete(tmp_path):
    body = doc(
        '<div class="section"><h2 id="a">A</h2>'
        '<p class="prose">Keep   this &amp; that.</p></div>'
    )
    passages = passages_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body})
    passage = passages[0]
    record = passage.to_dict()
    assert record["html"] == '<p class="prose">Keep   this &amp; that.</p>'
    assert record["text"] == "Keep this & that."
    assert record["heading"] == "A"
    assert record["breadcrumbs"] == []
    assert (record["document_href"], record["fragment"]) == ("text/ch.xhtml", "a")
    assert record["book_sha256"] == passage.section.book_sha256
    assert (record["grade"], record["language"], record["license"]) == (6, "en", "CC-BY")
    assert record["block_range"] == [1, 1]  # block 0 is the section heading itself
    assert record["id"].startswith("psg-") and len(record["id"]) == 20


def test_whole_document_section_owns_its_own_text(tmp_path):
    body = doc("<p>Front matter paragraph.</p><p>Second paragraph.</p>")
    epub, sections = sections_of(tmp_path, '<li><a href="fm.xhtml">Frontmatter</a></li>', {"fm.xhtml": body})
    assert (sections[0].fragment, sections[0].target_found) == ("", True)
    passages = extract_book_passages(epub, sections)
    assert "Front matter paragraph." in passages[0].text
    assert passages[0].section.title == "Frontmatter"


def test_chunks_respect_size_bounds_and_never_split_a_block(tmp_path):
    paragraphs = "".join(f"<p>{'word ' * 60}</p>" for _ in range(8))
    body = doc(f'<div class="section"><h2 id="a">A</h2>{paragraphs}</div>')
    passages = passages_of(
        tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body}, min_chars=200, max_chars=400
    )
    assert len(passages) > 1
    for passage in passages:
        assert len(passage.blocks) == 1  # every block is a whole paragraph
        assert len(passage.text) < 400
    assert all(len(passage.text) >= 200 for passage in passages)


def test_unsafe_image_src_is_kept_verbatim(tmp_path):
    body = doc(
        '<div class="section"><h2 id="a">A</h2>'
        '<p>Picture <img src="https://example.com/x.png" alt="remote"/> here.</p></div>'
    )
    passages = passages_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body})
    assert passages[0].images[0]["src"] == "https://example.com/x.png"
    assert passages[0].images[0]["alt"] == "remote"


def test_extraction_is_deterministic(tmp_path):
    epub, sections = sections_of(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC})
    first = [p.to_dict() for p in extract_book_passages(epub, sections, min_chars=1)]
    second = [p.to_dict() for p in extract_book_passages(epub, sections, min_chars=1)]
    assert first == second
    assert len({record["id"] for record in first}) == len(first)


def test_bad_sizes_rejected(tmp_path):
    body = doc('<div class="section"><h2 id="a">A</h2><p>Text.</p></div>')
    with pytest.raises(ValueError):
        passages_of(tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body}, min_chars=0)
    with pytest.raises(ValueError):
        passages_of(
            tmp_path, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": body}, min_chars=900, max_chars=100
        )


@needs_corpus
def test_grade6_electric_circuits_passages():
    catalog = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    grade6 = next(b for b in catalog["books"] if b["id"] == "natural-sciences-and-technology-6")
    epub = CORPUS / GRADE6_EPUB
    _record, sections = enumerate_book(epub, grade6)
    passages = extract_book_passages(epub, sections)
    assert len(passages) > 500
    index_sections(sections)

    by_title = {}
    for passage in passages:
        by_title.setdefault(passage.section.title, []).append(passage)
    parent_text = " ".join(p.text for p in by_title["Electric circuits"])
    assert len(by_title["Electric circuits"]) <= 5
    assert "simple electric circuit" in parent_text  # its own key questions
    assert "Many misconceptions develop" not in parent_text  # child prose stays in the child

    child_text = " ".join(p.text for p in by_title["A simple circuit"])
    assert "Many misconceptions develop" in child_text
    assert by_title["A simple circuit"][0].section.breadcrumbs == ["Electric circuits"]

    # Every section's blocks are numbered once per document: no excerpt is reused.
    seen: dict[str, set[int]] = {}
    for passage in passages:
        used = seen.setdefault(passage.section.document_href, set())
        for block in passage.blocks:
            assert block.ordinal not in used
            used.add(block.ordinal)

    # Grade 6 content is largely photographic: images are attached, not dropped.
    with_images = [p for p in passages if p.images]
    assert with_images
    assert all(not p.text_complete for p in with_images)


@needs_corpus
def test_grade10_maths_worked_examples_keep_equation_images():
    catalog = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    maths = next(b for b in catalog["books"] if b["id"] == "mathematics-10")
    epub = CORPUS / MATHS10_EPUB
    _record, sections = enumerate_book(epub, maths)
    passages = extract_book_passages(epub, sections, min_chars=400, max_chars=1200)
    titles = {section.title for section in sections}
    assert "Worked example 6: Simultaneous equations" not in titles

    substitution = [p for p in passages if p.section.title == "Solving by substitution"]
    assert substitution
    joined = " ".join(p.text for p in substitution)
    assert "Worked example 6: Simultaneous equations" in joined
    maths_images = [image for p in substitution for image in p.images]
    assert maths_images and all(image["kind"].startswith("math") for image in maths_images)
    assert any(not image["alt"] for image in maths_images)
    assert all(p.text_complete is False for p in substitution if p.images)

    # The original XHTML slice is verbatim: it is a substring of the source document.
    with zipfile.ZipFile(epub) as archive:
        documents = {href: archive.read(href).decode("utf-8") for href in {p.section.document_href for p in passages}}
    for passage in passages:
        record = passage.to_dict()
        assert record["html"] in documents[record["document_href"]]
        assert record["text"] or record["images"]

    records = [p.to_dict() for p in passages]
    assert len({record["id"] for record in records}) == len(records)


@needs_corpus
def test_catalogue_passages_are_deterministic_for_one_book():
    first, meta = extract_catalogue_passages(book_ids=["natural-sciences-and-technology-6"])
    second, _meta = extract_catalogue_passages(book_ids=["natural-sciences-and-technology-6"])
    assert meta["passage_count"] == len(first)
    assert [p.to_dict() for p in first] == [p.to_dict() for p in second]
    section_ids = {p.section.id for p in first}
    assert len(section_ids) > 100
