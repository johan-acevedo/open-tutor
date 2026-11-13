"""Focused tests for bounded original-source image feedback (step 4d).

A synthetic EPUB proves the resolver contract: only visible original images
(hidden teacher's-guide and grade 4-6 solution subtrees excluded), document
order, deduplication by file, known image media types, and the fixed
count/byte budget. A real-corpus probe compares the attached bytes with the
original EPUB members and proves that actual ``llm.ImageContent`` items are
constructed for the tutor without calling any paid provider.
"""

import base64
import hashlib
import json
import socket
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from livekit.agents import llm

from open_tutor.agent import Tutor
from open_tutor.materials import serving as serving_module
from open_tutor.materials.image_feedback import (
    MAX_IMAGES,
    MAX_TOTAL_BYTES,
    load_visible_image_feedback,
)
from open_tutor.materials.render import visible_scope
from open_tutor.materials.serving import SectionPackageStore, reset_material_store

CORPUS = Path.home() / ".local" / "share" / "open-tutor" / "materials" / "siyavula"
BOOKS_JSON = Path(__file__).resolve().parents[2] / "tools" / "siyavula" / "books.json"
GRADE6_CIRCUIT_ID = "sec-ecd16baf9e4fee44"
MATHS10_SUBSTITUTION_ID = "sec-6a9c825e9c3f2cd2"

needs_corpus = pytest.mark.skipif(
    not (CORPUS / "Gr6_NaturalSciences_Learner_Eng_CC-BY.epub").exists()
    or not (CORPUS / "Gr10_Mathematics_Learner_Eng_CC-BY.epub").exists()
    or not BOOKS_JSON.exists(),
    reason="downloaded Siyavula corpus is not present",
)

NAV = (
    '<li><a href="ch.xhtml#top">Images</a>'
    '<ol><li><a href="ch.xhtml#sub">Sub</a></li></ol></li>'
)
DOC = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
    '<link rel="stylesheet" type="text/css" href="a.css"/></head><body>'
    '<div class="section"><h1 id="top">Images</h1><p>Visible words.</p>'
    '<div class="teachers-guide"><p>Teacher planning.</p>'
    '<img src="img/teacher.png" alt=""/></div>'
    '<img class="math-block" src="equation/v1.png" alt=""/>'
    '<div class="solution"><p>Solution words.</p>'
    '<img src="img/solution.png" alt=""/></div>'
    '<img class="math-inline" src="equation/v2.png" alt=""/>'
    '<img src="equation/v1.png" alt=""/>'
    '<img src="img/photo.jpeg" alt=""/>'
    '<img src="img/diagram.svg" alt=""/>'
    '<div class="section"><h2 id="sub">Sub</h2><p>Child body words.</p>'
    '<img src="equation/v3.png" alt=""/></div>'
    "</div></body></html>"
)
# Distinct sizes so byte budgets are observable; bytes themselves are opaque.
ASSETS = {
    "a.css": b".math-block{}\n",
    "equation/v1.png": b"v1" * 300,  # 600 bytes
    "equation/v2.png": b"v2" * 350,  # 700 bytes
    "equation/v3.png": b"v3" * 450,  # 900 bytes
    "img/photo.jpeg": b"ph" * 400,  # 800 bytes
    "img/teacher.png": b"te" * 100,
    "img/solution.png": b"so" * 100,
    "img/diagram.svg": b"<svg/>\n",
}
VISIBLE_ORDER = [
    "equation/v1.png",
    "equation/v2.png",
    "img/photo.jpeg",
    "equation/v3.png",
]


def _write_epub(path: Path, doc: str = DOC, assets: dict[str, bytes] | None = None) -> None:
    assets = ASSETS if assets is None else assets
    manifest = "".join(
        f'<item id="a{i}" href="text/{name}" media-type="application/octet-stream"/>'
        for i, name in enumerate(assets)
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>t</dc:title></metadata>"
        '<manifest><item id="nav" href="text/nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="d0" href="text/ch.xhtml" media-type="application/xhtml+xml"/>'
        f"{manifest}</manifest>"
        '<spine><itemref idref="d0"/></spine></package>'
    )
    nav = (
        '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>n</title></head>'
        f'<body><nav epub:type="toc" id="toc"><ol>{NAV}</ol></nav></body></html>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
            'xmlns:container"><rootfiles><rootfile full-path="pkg.opf"/>'
            "</rootfiles></container>",
        )
        archive.writestr("pkg.opf", opf)
        archive.writestr("text/nav.xhtml", nav)
        archive.writestr("text/ch.xhtml", doc)
        for name, data in assets.items():
            archive.writestr(f"text/{name}", data)


def _synthetic_store(tmp_path: Path, grade: int = 6) -> SectionPackageStore:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    _write_epub(corpus / "tiny.epub")
    books = {
        "catalogue_url": "https://www.siyavula.com/read",
        "catalogue_license_url": "https://creativecommons.org/licenses/by/3.0/",
        "attribution": "Tiny test book.",
        "books": [
            {
                "id": "tiny-book",
                "title": "Tiny",
                "grade": grade,
                "language": "en",
                "license": "CC-BY",
                "url": "https://www.siyavula.com/read",
                "filename": "tiny.epub",
            }
        ],
    }
    books_path = tmp_path / "books.json"
    books_path.write_text(json.dumps(books), encoding="utf-8")
    return SectionPackageStore(
        data_dir=corpus, books_path=books_path, cache_root=tmp_path / "cache"
    )


@pytest.fixture(autouse=True)
def clean_material_store(monkeypatch):
    reset_material_store()
    monkeypatch.delenv("TUTOR_MATERIALS_DIR", raising=False)
    monkeypatch.delenv("TUTOR_MATERIALS_BOOKS", raising=False)
    monkeypatch.delenv("TUTOR_MATERIAL_CACHE", raising=False)
    yield
    reset_material_store()


def _patch_store(monkeypatch, store: SectionPackageStore):
    monkeypatch.setattr(
        serving_module, "material_store_for_process", lambda env=None: store
    )


def _section_id(store: SectionPackageStore) -> str:
    return next(
        section.id for section in store.resolver().sections.values() if section.title == "Images"
    )


def test_visible_scope_reuses_audited_hidden_selectors():
    markup = (
        '<root><div class="section"><p>T</p>'
        '<img src="teachers.png"/>'
        '<div class="teachers-guide"><img src="hidden-teacher.png"/></div>'
        '<div class="solution"><img src="hidden-solution.png"/></div>'
        "</div></root>"
    )
    _, grade6 = visible_scope(markup, hide_solutions=True)
    assert grade6 == ["teachers.png"]
    _, upper = visible_scope(markup, hide_solutions=False)
    # Upper-grade solutions stay visible; teacher guidance never does.
    assert upper == ["teachers.png", "hidden-solution.png"]


def test_hidden_images_are_never_attached(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store))
    paths = [image.package_path for image in feedback.images]
    assert paths == VISIBLE_ORDER
    assert "img/teacher.png" not in paths and "img/solution.png" not in paths
    # The only visible file left out is the non-image media type (svg).
    assert feedback.omitted == 1


def test_duplicate_files_are_attached_once_in_document_order(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store))
    assert [image.package_path for image in feedback.images] == VISIBLE_ORDER
    assert len({image.package_path for image in feedback.images}) == len(feedback.images)
    # The page counts six img tags (the duplicate included); only files dedupe.
    metadata = store.package(_section_id(store)).metadata
    assert metadata["visible_image_count"] == 6


def test_known_image_mime_only(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store))
    assert [image.mime for image in feedback.images] == [
        "image/png",
        "image/png",
        "image/jpeg",
        "image/png",
    ]
    assert all(image.data.startswith((b"v1", b"v2", b"ph", b"v3")) for image in feedback.images)


def test_count_budget_limits_attachments(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store), max_images=2)
    assert [image.package_path for image in feedback.images] == VISIBLE_ORDER[:2]
    assert feedback.omitted == 3


def test_total_byte_budget_limits_attachments(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store), max_total_bytes=1300)
    assert [image.package_path for image in feedback.images] == VISIBLE_ORDER[:2]
    assert feedback.total_bytes == 1300
    assert feedback.omitted == 3


def test_per_image_byte_budget_skips_large_images(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    feedback = load_visible_image_feedback(_section_id(store), max_image_bytes=650)
    assert [image.package_path for image in feedback.images] == VISIBLE_ORDER[:1]
    assert feedback.omitted == 4


def test_default_budget_is_small_and_fixed():
    assert MAX_IMAGES == 6
    assert MAX_TOTAL_BYTES == 2 * 1024 * 1024


def test_resolver_reads_no_network(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)

    def no_network(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("image feedback must not open a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    feedback = load_visible_image_feedback(_section_id(store))
    assert feedback.attached == 4


async def test_ack_gates_image_feedback(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    section_id = _section_id(store)
    calls: list[str] = []

    def spy(key):
        calls.append(key)
        raise AssertionError("an unacked page must not read image files")

    monkeypatch.setattr("open_tutor.agent.load_visible_image_feedback", spy)

    class Participant:
        async def perform_rpc(self, **kwargs):
            raise TimeoutError("no ack")

        async def set_attributes(self, attributes):
            pass

    class Room:
        local_participant = Participant()

    tutor = Tutor({"name": "Leo", "grade": 7}, Room())
    tutor.child_identity = "learner-1"
    update = AsyncMock()
    monkeypatch.setattr(tutor, "update_chat_ctx", update)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    await tutor.show_material(AsyncMock(), section_id=section_id)
    assert calls == []
    update.assert_not_awaited()
    assert tutor.chat_ctx.items == []


async def test_text_only_section_sends_no_image_message(monkeypatch):
    meta = {
        "title": "Words only",
        "heading": "Words only",
        "attribution": "Siyavula — Tiny — Words only — CC-BY — siyavula.com",
        "book": {"id": "tiny-book", "title": "Tiny"},
        "visible_text": "Only words here.",
        "visible_image_count": 0,
        "completeness": {"text_complete": True},
    }
    calls: list[str] = []

    def spy(key):
        calls.append(key)
        raise AssertionError("a text-only section has no image work to do")

    monkeypatch.setattr("open_tutor.agent.load_visible_image_feedback", spy)
    monkeypatch.setattr("open_tutor.agent.load_material_display", lambda key: meta)

    class Participant:
        async def perform_rpc(self, **kwargs):
            return '{"ok":true}'

        async def set_attributes(self, attributes):
            pass

    class Room:
        local_participant = Participant()

    tutor = Tutor({"name": "Leo", "grade": 7}, Room())
    tutor.child_identity = "learner-1"
    update = AsyncMock()
    monkeypatch.setattr(tutor, "update_chat_ctx", update)
    result = await tutor.show_material(AsyncMock(), section_id="sec-aaaaaaaaaaaaaaaa")
    assert "complete: no images" in result
    assert calls == [] and update.await_count == 0


@needs_corpus
async def test_real_source_image_bytes_match_original_epub(monkeypatch, tmp_path):
    monkeypatch.setenv("TUTOR_MATERIAL_CACHE", str(tmp_path / "cache"))
    for section_id in (GRADE6_CIRCUIT_ID, MATHS10_SUBSTITUTION_ID):
        feedback = load_visible_image_feedback(section_id)
        assert 0 < feedback.attached <= MAX_IMAGES
        assert feedback.omitted > 0  # a formula/figure-heavy page exceeds the budget
        assert feedback.total_bytes <= MAX_TOTAL_BYTES
        store = serving_module.material_store_for_process()
        package = store.package(section_id)
        metadata = package.metadata
        doc_dir = metadata["document_href"].rsplit("/", 1)[0]
        resolver = store.resolver()
        epub = resolver.epub_path_for(resolver.resolve(section_id))
        with zipfile.ZipFile(epub) as archive:
            for image in feedback.images:
                member = f"{doc_dir}/{image.package_path}" if doc_dir else image.package_path
                original = archive.read(member)
                assert hashlib.sha256(image.data).digest() == hashlib.sha256(original).digest()
                assert image.mime.startswith("image/")
                assert image.package_path in package.assets


@needs_corpus
async def test_real_substitution_images_become_image_content(monkeypatch, tmp_path):
    """Real EPUB bytes reach actual llm.ImageContent items; no provider is called."""
    monkeypatch.setenv("TUTOR_MATERIAL_CACHE", str(tmp_path / "cache"))

    class Participant:
        def __init__(self):
            self.calls = []

        async def perform_rpc(self, **kwargs):
            self.calls.append(kwargs)
            return '{"ok":true}'

        async def set_attributes(self, attributes):
            pass

    class Room:
        def __init__(self):
            self.local_participant = Participant()

    room = Room()
    tutor = Tutor({"name": "Leo", "grade": 10}, room)
    tutor.child_identity = "learner-1"
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=MATHS10_SUBSTITUTION_ID)
    # Display succeeded and the note reports the exact attached/omitted split.
    assert "Worked example" in result
    feedback = load_visible_image_feedback(MATHS10_SUBSTITUTION_ID)
    assert f"{feedback.attached} original source image(s)" in result
    assert f"{feedback.omitted} more visible image files were left out" in result
    assert "not a screenshot" in result and "current viewport" in result
    items = tutor.chat_ctx.items
    assert len(items) == 1 and items[0].role == "user"
    text, *images = items[0].content
    assert len(images) == feedback.attached
    assert all(isinstance(image, llm.ImageContent) for image in images)
    for image, source in zip(images, feedback.images):
        datas = image.image.removeprefix("data:")
        mime, _, payload = datas.partition(";base64,")
        assert mime == source.mime
        assert base64.b64decode(payload) == source.data
    assert MATHS10_SUBSTITUTION_ID in text
    assert f"page order 1-{feedback.attached}" in text
    assert "not a screenshot" in text and "current viewport" in text
