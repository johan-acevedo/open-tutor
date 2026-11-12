"""Behavioural tests for the Siyavula source catalogue (step 1).

Live-corpus tests read the real downloaded EPUBs and skip when the corpus is
absent. Synthetic-EPUB tests build a tiny book in a temp dir and always run.
"""

import json
import zipfile
from pathlib import Path

import pytest

from open_tutor.materials.catalogue import (
    enumerate_book,
    enumerate_catalogue,
    get_by_id,
    index_sections,
    safe_member,
    section_id,
)

CORPUS = Path.home() / ".local" / "share" / "open-tutor" / "materials" / "siyavula"
BOOKS_JSON = Path(__file__).resolve().parents[2] / "tools" / "siyavula" / "books.json"
GRADE6_EPUB = "Gr6_NaturalSciences_Learner_Eng_CC-BY.epub"
GRADE6_SHA = "87d28ca7362de99fbf4d70f9b547f5640938adc1e8130f7d6b11ccce77d95264"
MATHS10_EPUB = "Gr10_Mathematics_Learner_Eng_CC-BY.epub"

needs_corpus = pytest.mark.skipif(
    not (CORPUS / GRADE6_EPUB).exists() or not BOOKS_JSON.exists(),
    reason="downloaded Siyavula corpus is not present",
)


def _write_epub(path: Path, nav_items: str, docs: dict[str, str]) -> None:
    """Write a minimal EPUB 3 with a manifest nav and content documents."""
    manifest = "".join(
        f'<item id="d{i}" href="text/{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(docs)
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        "<metadata xmlns:dc=\"http://purl.org/dc/elements/1.1/\">"
        "<dc:title>t</dc:title></metadata>"
        f"<manifest><item id=\"nav\" href=\"text/nav.xhtml\" "
        'media-type="application/xhtml+xml" properties="nav"/>'
        f"{manifest}</manifest>"
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
        archive.writestr("pkg.opf", opf)
        archive.writestr("text/nav.xhtml", nav)
        for name, body in docs.items():
            archive.writestr(f"text/{name}", body)


def _book(book_id="tiny-book", sha=None, **overrides):
    book = {
        "id": book_id,
        "title": "Tiny",
        "filename": "tiny.epub",
        "grade": 6,
        "language": "en",
        "url": "https://www.siyavula.com/read",
        "license": "CC-BY",
    }
    if sha:
        book["sha256"] = sha
    book.update(overrides)
    return book


def test_nav_is_authoritative_nested_headings_do_not_split(tmp_path):
    """A worked-example style nested h3 inside a section must not create records."""
    nav_items = (
        '<li><a href="ch.xhtml#top">Top</a><ol>'
        '<li><a href="ch.xhtml#sub">Worked example</a></li></ol></li>'
    )
    doc = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
        '<link rel="stylesheet" type="text/css" href="./style.css"/></head><body>'
        '<h1 id="top">Top</h1><h3>Worked example inner heading without id</h3>'
        '<h2 id="sub">Worked example</h2></body></html>'
    )
    epub = tmp_path / "tiny.epub"
    _write_epub(epub, nav_items, {"ch.xhtml": doc, "style.css": "h1{}"})
    record, sections = enumerate_book(epub, _book())
    assert record.section_count == 2
    assert [s.title for s in sections] == ["Top", "Worked example"]
    assert sections[1].breadcrumbs == ["Top"]
    assert sections[1].document_href == "text/ch.xhtml"
    assert sections[0].stylesheets == ["text/style.css"]
    assert all(s.target_found for s in sections)


def test_section_id_derives_from_book_sha_and_location(tmp_path):
    epub = tmp_path / "tiny.epub"
    _write_epub(epub, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": _DOC_A})
    _record, sections = enumerate_book(epub, _book())
    # The recorded SHA is the real file digest, and the ID derives from it.
    digest = sections[0].book_sha256
    assert len(digest) == 64
    assert sections[0].id == section_id(digest, "text/ch.xhtml", "a")


_DOC_A = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
    '<h1 id="a">A</h1></body></html>'
)


def test_duplicate_ids_rejected():
    first = _book()
    assert str(index_sections([])) == "{}"
    with pytest.raises(ValueError):
        index_sections([first_section(), first_section()])


def first_section():
    from open_tutor.materials.catalogue import SectionRef

    return SectionRef(id="sec-x", book_id="b", title="T")


def test_unsafe_nav_hrefs_rejected():
    with pytest.raises(ValueError):
        safe_member("text/", "https://example.com/evil.xhtml#f")
    with pytest.raises(ValueError):
        safe_member("text/", "../../evil.xhtml")
    with pytest.raises(ValueError):
        safe_member("text/", "/absolute.xhtml")
    member, frag = safe_member("text/", "sub/ch.xhtml#s1")
    assert (member, frag) == ("text/sub/ch.xhtml", "s1")


def test_hostile_nav_cannot_escape_archive(tmp_path):
    epub = tmp_path / "tiny.epub"
    _write_epub(epub, '<li><a href="../evil.xhtml">Evil</a></li>', {"ch.xhtml": _DOC_A})
    with pytest.raises(ValueError):
        enumerate_book(epub, _book())


def test_get_by_id_round_trip_and_unknown(tmp_path):
    epub = tmp_path / "tiny.epub"
    _write_epub(epub, '<li><a href="ch.xhtml#a">A</a></li>', {"ch.xhtml": _DOC_A})
    _record, sections = enumerate_book(epub, _book())
    assert get_by_id(sections, sections[0].id).title == "A"
    with pytest.raises(KeyError):
        get_by_id(sections, "sec-nope")


@needs_corpus
def test_grade6_electric_circuits_against_real_epub():
    catalog = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    book = next(b for b in catalog["books"] if b["id"] == "natural-sciences-and-technology-6")
    record, sections = enumerate_book(CORPUS / GRADE6_EPUB, book, ["http://creativecommons.org/licenses/by/4.0/"])
    assert record.sha256 == GRADE6_SHA == book["sha256"]
    by_title = {s.title: s for s in sections}
    top = by_title["Electric circuits"]
    assert top.breadcrumbs == []
    assert top.document_href == "OPS/xhtml/Grade-6/ec.xhtml"
    assert top.fragment == "toc-id-0"
    sub = by_title["A simple circuit"]
    assert sub.breadcrumbs == ["Electric circuits"]
    assert (sub.document_href, sub.fragment) == ("OPS/xhtml/Grade-6/ec.xhtml", "toc-id-1")
    for section in (top, sub):
        assert section.grade == 6 and section.language == "en"
        assert section.source_url == book["url"] and section.license == "CC-BY"
        assert section.license_evidence == ["http://creativecommons.org/licenses/by/4.0/"]
        assert section.target_found
        assert section.stylesheets == ["OPS/xhtml/Grade-6/custom.css"]
        assert section.id == section_id(GRADE6_SHA, section.document_href, section.fragment)


@needs_corpus
def test_grade10_maths_against_real_epub():
    catalog = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    book = next(b for b in catalog["books"] if b["id"] == "mathematics-10")
    _record, sections = enumerate_book(CORPUS / MATHS10_EPUB, book)
    assert len(sections) > 100
    first = sections[0]
    assert first.title == "1.1 Introduction"
    assert first.document_href.endswith("01-algebraic-expressions-00.cnxmlplus.html")
    assert first.fragment == "toc-id-1"
    assert first.grade == 10
    assert all(s.target_found for s in sections)
    index_sections(sections)


@needs_corpus
def test_full_corpus_deterministic_and_unique():
    first = enumerate_catalogue(data_dir=CORPUS, books_path=BOOKS_JSON)
    second = enumerate_catalogue(data_dir=CORPUS, books_path=BOOKS_JSON)
    dump = lambda result: json.dumps(
        {
            "books": [b.to_dict() for b in result[0]],
            "sections": [s.to_dict() for s in result[1]],
            "meta": result[2],
        },
        sort_keys=True,
    )
    assert dump(first) == dump(second)
    _books, sections, _meta = first
    assert len(sections) > 1000
    index_sections(sections)  # raises on duplicate IDs
    assert all(s.target_found for s in sections)
