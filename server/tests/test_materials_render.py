"""Behavioural tests for original-section rendering (step 3a).

Synthetic-EPUB tests pin the display rules (descendant inclusion, peer
exclusion, sanitizer, allowlist, determinism). Live-corpus tests prove the
two contracted sections against the real pinned books and skip when the
corpus is absent.
"""

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from open_tutor.materials.render import (
    SectionResolver,
    build_index_html,
    export_package,
    render_section,
    sanitize_slice,
    validate_package,
)

CORPUS = Path.home() / ".local" / "share" / "open-tutor" / "materials" / "siyavula"
BOOKS_JSON = Path(__file__).resolve().parents[2] / "tools" / "siyavula" / "books.json"

GRADE6_CIRCUIT_ID = "sec-ecd16baf9e4fee44"  # A simple circuit
MATHS10_SUBSTITUTION_ID = "sec-6a9c825e9c3f2cd2"  # Solving by substitution

needs_corpus = pytest.mark.skipif(
    not (CORPUS / "Gr6_NaturalSciences_Learner_Eng_CC-BY.epub").exists()
    or not (CORPUS / "Gr10_Mathematics_Learner_Eng_CC-BY.epub").exists()
    or not BOOKS_JSON.exists(),
    reason="downloaded Siyavula corpus is not present",
)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
)


def _write_epub(path: Path, nav_items: str, docs: dict[str, str], assets: dict[str, bytes]) -> None:
    manifest = "".join(
        f'<item id="d{i}" href="text/{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(docs)
    )
    manifest += "".join(
        f'<item id="a{i}" href="text/{name}" media-type="application/octet-stream"/>'
        for i, name in enumerate(assets)
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>t</dc:title></metadata>"
        f'<manifest><item id="nav" href="text/nav.xhtml" '
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
        for name, data in assets.items():
            archive.writestr(f"text/{name}", data)


def _resolver(tmp_path: Path, nav_items: str, docs: dict, assets: dict | None = None) -> SectionResolver:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True)
    _write_epub(corpus / "tiny.epub", nav_items, docs, assets or {})
    books = {
        "catalogue_url": "https://www.siyavula.com/read",
        "catalogue_license_url": "https://creativecommons.org/licenses/by/3.0/",
        "attribution": "Tiny test book.",
        "books": [
            {
                "id": "tiny-book",
                "title": "Tiny",
                "grade": 6,
                "language": "en",
                "license": "CC-BY",
                "url": "https://www.siyavula.com/read",
                "filename": "tiny.epub",
            }
        ],
    }
    books_path = tmp_path / "books.json"
    books_path.write_text(json.dumps(books), encoding="utf-8")
    return SectionResolver(data_dir=corpus, books_path=books_path)


NESTED_NAV = (
    '<li><a href="ch.xhtml#top">Top</a><ol>'
    '<li><a href="ch.xhtml#sub">Sub</a></li></ol></li>'
    '<li><a href="ch.xhtml#peer">Peer</a></li>'
)
NESTED_DOC = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
    '<link rel="stylesheet" type="text/css" href="b.css"/>'
    '<link rel="stylesheet" type="text/css" href="a.css"/></head><body>'
    '<div class="section"><h1 class="title" id="top">Top</h1><p>Parent intro.</p>'
    '<div class="section"><h2 class="title" id="sub">Sub</h2><p>Child body.</p>'
    '<img class="math-inline" src="equation/e1.png" alt=""/>'
    "</div><p>Parent tail.</p></div>"
    '<div class="section"><h2 class="title" id="peer">Peer</h2><p>Peer body.</p></div>'
    "</body></html>"
)
NESTED_ASSETS = {"b.css": b"h1{}", "a.css": b"h2{}", "equation/e1.png": PNG}


def _ids(resolver: SectionResolver) -> dict[str, str]:
    return {section.title: section.id for section in resolver.sections.values()}


def test_parent_slice_includes_child_and_excludes_peer(tmp_path):
    resolver = _resolver(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC}, NESTED_ASSETS)
    ids = _ids(resolver)
    parent = render_section(resolver, ids["Top"])
    assert "Parent intro." in parent.slice_html and "Parent tail." in parent.slice_html
    assert "Child body." in parent.slice_html  # descendants render with the parent
    assert "Peer body." not in parent.slice_html
    assert [child.title for child in parent.descendants] == ["Sub"]
    child = render_section(resolver, ids["Sub"])
    assert "Child body." in child.slice_html
    assert "Parent intro." not in child.slice_html and "Peer body." not in child.slice_html
    assert child.descendants == []
    peer = render_section(resolver, ids["Peer"])
    assert "Peer body." in peer.slice_html and "Child body." not in peer.slice_html
    # Slices are balanced: each parses as well-formed XML on its own.
    from open_tutor.materials.passages import parse_document as parse

    for rendered in (parent, child, peer):
        parse(f'<root xmlns="http://www.w3.org/1999/xhtml">{rendered.slice_html}</root>'.encode())


def test_stylesheet_order_preserved_and_active_content_stripped(tmp_path):
    doc = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
        '<link rel="stylesheet" href="b.css"/><link rel="stylesheet" href="a.css"/>'
        '<script type="text/javascript" src="mathjax/MathJax.js"> </script></head><body>'
        '<div class="section"><h1 id="top">Top</h1>'
        '<p onclick="steal()">Hi <a href="javascript:alert(1)">x</a></p>'
        '<script>alert("inline")</script></div></body></html>'
    )
    resolver = _resolver(
        tmp_path, '<li><a href="ch.xhtml#top">Top</a></li>', {"ch.xhtml": doc},
        {"b.css": b"h1{}", "a.css": b"h2{}"},
    )
    out = tmp_path / "pkg"
    metadata = export_package(resolver, _ids(resolver)["Top"], out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert index.index('href="b.css"') < index.index('href="a.css"')
    assert "<script" not in index.lower() and "onclick" not in index
    assert "javascript:" not in index and "#blocked" in index
    assert "MathJax" not in index
    assert metadata["sanitize_notes"]
    assert (out / "b.css").exists() and (out / "a.css").exists()
    assert validate_package(out, metadata) == []


def test_stale_nav_target_renders_at_corrected_heading(tmp_path):
    doc = (
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title></head><body>'
        '<div class="section"><h1 id="chapter">Chapter 6: Functions</h1>'
        '<h3 id="variables">Variables</h3><p>Var body.</p></div></body></html>'
    )
    resolver = _resolver(
        tmp_path,
        '<li><span>Chapter 6: Functions</span><ol>'
        '<li><a href="ch.xhtml#chapter">Variables</a></li></ol></li>',
        {"ch.xhtml": doc},
    )
    section = next(iter(resolver.sections.values()))
    assert section.fragment == "variables"  # catalogue corrected the stale target
    assert section.source_href == "ch.xhtml#chapter"
    rendered = render_section(resolver, section.id)
    assert "Var body." in rendered.slice_html


def test_unknown_id_and_unsafe_refs(tmp_path):
    resolver = _resolver(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC}, NESTED_ASSETS)
    with pytest.raises(KeyError):
        render_section(resolver, "sec-nope")
    ids = _ids(resolver)
    out = tmp_path / "pkg"
    unsafe = NESTED_DOC.replace('Child body.', 'Child body.<img src="../../../../etc/passwd"/>')
    resolver = _resolver(tmp_path / "unsafe", NESTED_NAV, {"ch.xhtml": unsafe}, NESTED_ASSETS)
    with pytest.raises(ValueError, match="Unresolved"):
        export_package(resolver, _ids(resolver)["Sub"], out)
    assert not out.exists()


def test_heading_number_suppression_follows_document_start(tmp_path):
    resolver = _resolver(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC}, NESTED_ASSETS)
    ids = _ids(resolver)
    top = render_section(resolver, ids["Top"])
    assert top.suppress_heading_numbers is False
    assert "content: none" not in build_index_html(top)
    for title in ("Sub", "Peer"):
        rendered = render_section(resolver, ids[title])
        assert rendered.suppress_heading_numbers is True
        page = build_index_html(rendered)
        # Equal-specificity override, placed after the book links, that
        # hides generated heading numbers without touching text labels.
        assert "div.section > h1.title:before" in page
        assert "div.section > h2.title:before" in page
    assert top.slice_html  # suppression never rewrites original markup


@needs_corpus
def test_grade6_circuit_slice_hides_zero_number_not_book_number(tmp_path):
    resolver = SectionResolver()
    circuit = render_section(resolver, GRADE6_CIRCUIT_ID)
    assert circuit.suppress_heading_numbers is True
    assert "0.0" not in circuit.slice_html  # the artifact was never in the markup
    assert "content: none" in build_index_html(circuit)
    first = render_section(resolver, "sec-18d8044ce2b17e5a")  # Electric circuits
    assert first.suppress_heading_numbers is False


def test_export_is_deterministic(tmp_path):
    resolver = _resolver(tmp_path, NESTED_NAV, {"ch.xhtml": NESTED_DOC}, NESTED_ASSETS)
    first = export_package(resolver, _ids(resolver)["Top"], tmp_path / "a")
    second = export_package(resolver, _ids(resolver)["Top"], tmp_path / "b")
    assert first == second
    for entry in first["files"]:
        left = (tmp_path / "a" / Path(*Path(entry["path"]).parts)).read_bytes()
        right = (tmp_path / "b" / Path(*Path(entry["path"]).parts)).read_bytes()
        assert left == right
    assert (tmp_path / "a" / "metadata.json").read_bytes() == (
        tmp_path / "b" / "metadata.json"
    ).read_bytes()


def test_sanitize_slice_notes():
    cleaned, notes = sanitize_slice('<p onclick="x()">a</p><script>b</script>')
    assert "<script" not in cleaned and "onclick" not in cleaned
    assert len(notes) == 2


@needs_corpus
def test_grade6_simple_circuit_keeps_illustration_excludes_peer(tmp_path):
    resolver = SectionResolver()
    rendered = render_section(resolver, GRADE6_CIRCUIT_ID)
    assert rendered.section.title == "A simple circuit"
    assert rendered.section.breadcrumbs == ["Electric circuits"]
    assert "Many misconceptions develop" not in rendered.visible_text
    assert "Many misconceptions develop" in rendered.owned_text
    assert "Many misconceptions develop" in rendered.slice_html
    assert "Circuit components" in rendered.slice_html  # intentional descendant
    assert "Circuit diagrams" not in rendered.slice_html  # next peer excluded
    assert "toc-id-3" not in rendered.slice_html
    assert [child.title for child in rendered.descendants] == ["Circuit components"]
    assert rendered.section.license_evidence  # embedded license links surfaced
    out = tmp_path / "circuit"
    metadata = export_package(resolver, GRADE6_CIRCUIT_ID, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    circuit_images = [image for image in metadata["images"] if "ec-gd-" in image["src"]]
    assert len(circuit_images) >= 10 and all(image["resolved"] for image in metadata["images"] if not image["src"].startswith("http"))
    for image in circuit_images:
        assert image["src"] in index and (out / Path(*Path(image["package_path"]).parts)).is_file()
    assert metadata["stylesheets"][0]["href"].endswith("custom.css")
    assert 'href="./custom.css"' in index or 'href="custom.css"' in index
    assert validate_package(out, metadata) == []


@needs_corpus
def test_grade10_substitution_keeps_worked_example_and_equations(tmp_path):
    resolver = SectionResolver()
    rendered = render_section(resolver, MATHS10_SUBSTITUTION_ID)
    assert rendered.section.title == "Solving by substitution"
    assert "Worked example 6" in rendered.slice_html  # worked example preserved
    assert "Solving by elimination" not in rendered.slice_html  # next peer excluded
    assert "toc-id-1" not in rendered.slice_html
    equations = [image for image in rendered.images if "equation/" in image.ref]
    assert len(equations) == 29
    assert all(image.kind.startswith("math") for image in equations)
    out = tmp_path / "substitution"
    metadata = export_package(resolver, MATHS10_SUBSTITUTION_ID, out)
    assert all(image["resolved"] for image in metadata["images"])
    assert all(image["kind"].startswith("math") for image in metadata["images"])
    assert "Worked example 6" in (out / "index.html").read_text(encoding="utf-8")
    assert validate_package(out, metadata) == []
    assert rendered.section.license_evidence
    assert "Worked example 6" in rendered.owned_text
    assert not rendered.text_complete  # math lives in images, not text


def test_visible_feedback_matches_scope_and_hidden_selectors():
    from open_tutor.materials.render import visible_feedback
    markup = '<div><p>Student intro</p><div class="teachers-guide">Secret teacher</div><div class="solution">Answer</div><div class="section"><h2>Child</h2><p>Child text<img src="eq.png"/></p></div></div>'
    text, images = visible_feedback(markup, hide_solutions=True)
    assert 'Student intro' in text and 'Child text' in text
    assert 'Secret teacher' not in text and 'Answer' not in text
    assert images == 1
    text, _ = visible_feedback(markup, hide_solutions=False)
    assert 'Answer' in text


@pytest.mark.parametrize('addition', ['<iframe src="https://example.com"/>', '<img src="x" srcset="https://example.com 2x"/>', '<p style="background:url(https://example.com)">x</p>'])
def test_unsupported_automatic_fetches_refused(addition):
    from open_tutor.materials.render import assert_inert_source
    with pytest.raises(ValueError):
        assert_inert_source('<root>' + addition + '</root>')


@needs_corpus
def test_parent_feedback_includes_visible_math_descendants():
    rendered = render_section(SectionResolver(), 'sec-83e2150c0737cec5')
    assert len(rendered.visible_text) > 1000
    assert rendered.visible_image_count > 100
    assert not rendered.text_complete


def test_export_requires_fresh_directory(tmp_path):
    resolver = _resolver(tmp_path, NESTED_NAV, {'ch.xhtml': NESTED_DOC}, NESTED_ASSETS)
    out = tmp_path / 'out'
    export_package(resolver, _ids(resolver)['Top'], out)
    with pytest.raises(ValueError, match='fresh empty'):
        export_package(resolver, _ids(resolver)['Top'], out)


def test_export_preserves_body_styling_attributes(tmp_path):
    doc = NESTED_DOC.replace('<body>', '<body class="energyandchange" lang="en" dir="ltr" id="not-copied">')
    resolver = _resolver(tmp_path, NESTED_NAV, {'ch.xhtml': doc}, NESTED_ASSETS)
    out = tmp_path / 'body-style'
    section_id = _ids(resolver)['Top']
    export_package(resolver, section_id, out)
    page = (out / 'index.html').read_text()
    assert 'class="energyandchange"' in page
    assert 'dir="ltr"' in page
    assert f'data-material-section="{section_id}"' in page
    assert 'id="not-copied"' not in page
