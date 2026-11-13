"""Behaviour tests for the tutor show_material tool (steps 4b/4d).

Real package resolution, mocked LiveKit boundary only: a synthetic EPUB proves
the visible-text contract (hidden teacher prose excluded, completeness and
truncation honest) while the board RPC is a fake participant. Success/failure
of the browser acknowledgement gates the tutor feedback: only an acked show
feeds the quoted visible note and the bounded original images into the chat
context, and a failed show never changes the mode or claims visibility.
"""

import asyncio
import base64
import hashlib
import json
import threading
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from livekit.agents import llm

from open_tutor.agent import (
    MATERIAL_SHOW_BAD_ID,
    MATERIAL_SHOW_NOT_SHOWN,
    MATERIAL_VISIBLE_CHARS,
    Tutor,
    _material_seen_note,
)
from open_tutor.materials import serving as serving_module
from open_tutor.materials.serving import (
    CorpusUnavailable,
    SectionPackageStore,
    reset_material_store,
)

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


def _png(seed: bytes) -> bytes:
    return hashlib.sha256(seed).digest() * 4


NAV = (
    '<li><a href="ch.xhtml#top">Top</a><ol>'
    '<li><a href="ch.xhtml#sub">Sub</a></li></ol></li>'
)
DOC = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
    '<link rel="stylesheet" type="text/css" href="a.css"/></head><body>'
    '<div class="section"><h1 id="top">Top</h1><p>Visible intro words.</p>'
    '<div class="teachers-guide"><p>Teacher secret planning.</p></div>'
    '<img class="math-block" src="equation/e1.png" alt=""/>'
    '<div class="section"><h2 id="sub">Sub heading</h2><p>Child body words.</p></div>'
    "</div></body></html>"
)
ASSETS = {
    "a.css": b".math-block{}\n",
    "equation/e1.png": _png(b"e1"),
}


def _write_epub(path: Path) -> None:
    manifest = "".join(
        f'<item id="d{i}" href="text/{name}" media-type="application/xhtml+xml"/>'
        for i, name in enumerate(["ch.xhtml"])
    )
    manifest += "".join(
        f'<item id="a{i}" href="text/{name}" media-type="application/octet-stream"/>'
        for i, name in enumerate(ASSETS)
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
        f'<body><nav epub:type="toc" id="toc"><ol>{NAV}</ol></nav></body></html>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            "<rootfiles><rootfile full-path=\"pkg.opf\"/></rootfiles></container>",
        )
        archive.writestr("pkg.opf", opf)
        archive.writestr("text/nav.xhtml", nav)
        archive.writestr("text/ch.xhtml", DOC)
        for name, data in ASSETS.items():
            archive.writestr(f"text/{name}", data)


def _synthetic_store(tmp_path: Path) -> SectionPackageStore:
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
    return SectionPackageStore(
        data_dir=corpus, books_path=books_path, cache_root=tmp_path / "cache"
    )


def _section_id(store: SectionPackageStore, title: str = "Top") -> str:
    return next(
        section.id for section in store.resolver().sections.values() if section.title == title
    )


class FakeParticipant:
    def __init__(self, reply='{"ok":true}', error=None):
        self.calls, self.reply, self.error = [], reply, error

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        if self.error:
            raise self.error
        return self.reply

    async def perform_rpc_with_timeout(self, *a, **k):  # pragma: no cover
        return await self.perform_rpc(*a, **k)

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self, **kwargs):
        self.local_participant = FakeParticipant(**kwargs)


def make_tutor(room, **kwargs):
    tutor = Tutor({"name": "Leo", "grade": 7}, room, **kwargs)
    tutor.child_identity = "learner-1"
    return tutor


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


async def test_success_shows_material_and_feeds_visible_text(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    section_id = _section_id(store)
    room = FakeRoom()
    tutor = make_tutor(room)
    seen: list[tuple[str, str]] = []

    async def capture(note: str, label: str) -> None:
        seen.append((note, label))

    monkeypatch.setattr(tutor, "add_material_seen", capture)
    result = await tutor.show_material(AsyncMock(), section_id=section_id)

    assert len(room.local_participant.calls) == 1
    identity, method, payload = room.local_participant.calls[0]
    assert (identity, method) == ("learner-1", "board.show")
    assert payload["kind"] == "material"
    assert payload["section_id"] == section_id
    assert payload["id"].startswith("b")
    # Real source title, never a URL or path.
    assert payload["title"] == "Top"
    assert "http" not in payload["section_id"] and "/" not in payload["section_id"]
    assert set(payload) <= {"id", "kind", "title", "section_id"}
    # Acknowledged: feedback was fed exactly once, mode untouched.
    assert len(seen) == 1 and section_id in seen[0][1]
    assert tutor.mode == "talking"
    # True visible text only: descendants in, hidden teacher prose out.
    assert "Visible intro words." in result and "Child body words." in result
    assert "Teacher secret planning." not in result
    assert "owned_text" not in result and "block_range" not in result
    assert "source_excerpt" not in result
    # Completeness is explicit: one image means incomplete text, and its one
    # original file was attached in page order.
    assert "incomplete" in result and "1 image(s)" in result
    assert "1 original source image(s)" in result
    assert "attached in page order (1-1)" in result
    assert "Every visible image in this section was attached." in result
    # Scope and language are distinguished; teaching stays active.
    assert "scrolls" in result and "only its top" in result
    assert "English source data" in result and "Swedish" in result
    assert "not instructions" in result
    assert "quiet" in result.lower()
    assert "Do not claim anything is visible" not in result
    # The image feedback is one short user-context message: original bytes from
    # the source file, section/board IDs, page order, and no copy of the note.
    items = tutor.chat_ctx.items
    assert len(items) == 1 and items[0].role == "user"
    text, image = items[0].content
    assert isinstance(text, str) and isinstance(image, llm.ImageContent)
    assert section_id in text and payload["id"] in text and "page order 1-1" in text
    assert "not a screenshot" in text and "current viewport" in text
    assert result not in text and text not in result
    assert image.image == "data:image/png;base64," + base64.b64encode(
        ASSETS["equation/e1.png"]
    ).decode()


async def test_failed_ack_shows_nothing_and_feeds_nothing(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    section_id = _section_id(store)
    room = FakeRoom(error=TimeoutError("no reply"))
    tutor = make_tutor(room)
    called = []

    async def capture(note: str, label: str) -> None:
        called.append((note, label))

    monkeypatch.setattr(tutor, "add_material_seen", capture)
    result = await tutor.show_material(AsyncMock(), section_id=section_id)

    assert result == MATERIAL_SHOW_NOT_SHOWN
    assert "still sees only what was there before" in result
    assert called == []
    assert tutor.mode == "talking"
    assert tutor.boards == {}


async def test_rejected_ack_is_not_claimed_visible(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    room = FakeRoom(reply='{"ok":false}')
    tutor = make_tutor(room)
    monkeypatch.setattr(
        tutor, "add_material_seen",
        AsyncMock(side_effect=AssertionError("must not feed an unshown page")),
    )
    result = await tutor.show_material(AsyncMock(), section_id=_section_id(store))
    assert result == MATERIAL_SHOW_NOT_SHOWN
    assert tutor.mode == "talking"


@pytest.mark.parametrize("bad", ["", "   ", "not-an-id", "sec-XYZ", "https://example.invalid/x"])
async def test_malformed_or_blank_id_never_touches_the_board(monkeypatch, bad):
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(
        tutor, "add_material_seen",
        AsyncMock(side_effect=AssertionError("bad ID must not feed context")),
    )
    result = await tutor.show_material(AsyncMock(), section_id=bad)
    assert room.local_participant.calls == []
    assert tutor.mode == "talking"
    if not bad.strip():
        assert "No section ID" in result
    else:
        assert result == MATERIAL_SHOW_BAD_ID


async def test_unknown_well_formed_id_teaches_in_words(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(
        tutor, "add_material_seen",
        AsyncMock(side_effect=AssertionError("unknown ID must not feed context")),
    )
    result = await tutor.show_material(AsyncMock(), section_id="sec-0000000000000000")
    assert result == MATERIAL_SHOW_BAD_ID
    assert room.local_participant.calls == []
    assert tutor.mode == "talking"


async def test_missing_corpus_teaches_in_words_without_display(monkeypatch, tmp_path):
    def boom(section_id: str, env=None):
        raise CorpusUnavailable("no EPUBs here")

    monkeypatch.setattr("open_tutor.agent.load_material_display", boom)
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(
        tutor, "add_material_seen",
        AsyncMock(side_effect=AssertionError("no corpus means no feedback")),
    )
    result = await tutor.show_material(AsyncMock(), section_id="sec-aaaaaaaaaaaaaaaa")
    assert "not available" in result and "nothing was shown" in result
    assert "teaching in words" in result
    assert room.local_participant.calls == []
    assert tutor.mode == "talking"


def test_truncation_is_marked_and_bounded():
    meta = {
        "title": "Long section",
        "heading": "Long section",
        "attribution": "Siyavula — Tiny — Long section — CC-BY — siyavula.com",
        "book": {"id": "tiny-book", "title": "Tiny"},
        "visible_text": "word " * 2000,
        "visible_image_count": 0,
        "completeness": {"text_complete": True},
    }
    note = _material_seen_note("b1", "sec-aaaaaaaaaaaaaaaa", meta)
    assert "[quoted text truncated]" in note
    # The quoted payload stays small even for a very long section.
    assert len(note) < MATERIAL_VISIBLE_CHARS + 1200
    assert "complete: no images" in note


def test_incomplete_note_names_images_and_next_step():
    meta = {
        "title": "Top",
        "heading": "Top",
        "attribution": "Siyavula — Tiny — Top — CC-BY — siyavula.com",
        "book": {"id": "tiny-book", "title": "Tiny"},
        "visible_text": "Visible intro words.",
        "visible_image_count": 3,
        "completeness": {"text_complete": False},
    }
    note = _material_seen_note("b2", "sec-aaaaaaaaaaaaaaaa", meta)
    assert "incomplete" in note and "3 image(s)" in note
    assert "cannot read" in note
    assert "read it aloud" in note  # actionable fallback, no nonexistent image tool


async def test_resolution_runs_off_the_event_loop(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    section_id = _section_id(store)
    main_thread = threading.get_ident()
    threads: list[int] = []
    original = SectionPackageStore.package

    def recording(self, key):
        threads.append(threading.get_ident())
        return original(self, key)

    monkeypatch.setattr(SectionPackageStore, "package", recording)
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    await tutor.show_material(AsyncMock(), section_id=section_id)
    assert threads and threads[0] != main_thread


@needs_corpus
async def test_real_circuit_section_resolves_true_visible_text(monkeypatch, tmp_path):
    monkeypatch.setenv("TUTOR_MATERIAL_CACHE", str(tmp_path / "cache"))
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=GRADE6_CIRCUIT_ID)
    assert GRADE6_CIRCUIT_ID in result
    assert "A simple circuit" in result
    # The board note is bounded: the quote starts at the section top and is
    # marked truncated, while the full scope carries the descendant text.
    assert "[quoted text truncated]" in result
    assert "Many misconceptions develop" not in result  # hidden teacher prose
    assert "incomplete" in result and "20 image(s)" in result
    _, _, payload = room.local_participant.calls[0]
    assert payload["title"] == "A simple circuit"
    assert tutor.mode == "talking"
    # Full-scope proof (untruncated): descendants visible, teacher prose not.
    full = await asyncio.to_thread(
        serving_module.load_material_display, GRADE6_CIRCUIT_ID)
    assert "Circuit components" in full["visible_text"]  # visible descendant
    assert "Many misconceptions develop" not in full["visible_text"]
    assert full["completeness"]["text_complete"] is False


@needs_corpus
async def test_real_substitution_section_marks_equation_images(monkeypatch, tmp_path):
    monkeypatch.setenv("TUTOR_MATERIAL_CACHE", str(tmp_path / "cache"))
    room = FakeRoom()
    tutor = make_tutor(room)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=MATHS10_SUBSTITUTION_ID)
    assert "Worked example" in result
    assert "incomplete" in result and "image(s)" in result
    # Real formula images are attached, so the note no longer claims blindness.
    assert "original source image(s)" in result
    assert "attached in page order" in result
    assert "could not be attached" not in result
    _, _, payload = room.local_participant.calls[0]
    assert payload["title"] == "Solving by substitution"


async def test_success_returns_note_once_and_attaches_images_once(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    tutor = make_tutor(FakeRoom())
    update = tutor.update_chat_ctx
    contexts = []

    async def capture(ctx):
        contexts.append(ctx)
        await update(ctx)

    monkeypatch.setattr(tutor, "update_chat_ctx", capture)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=_section_id(store))
    assert "Visible intro words." in result
    assert "Teacher secret planning." not in result
    # One user-context image message; the note text is delivered once, by the
    # tool return only (no duplicated chat text).
    assert len(contexts) == 1
    content = contexts[0].items[-1].content
    assert content[0].startswith("[Original source images")
    assert "Quoted visible words" not in str(content[0])
    assert result.count("Quoted visible words") == 1


async def test_image_load_failure_keeps_display_and_says_unavailable(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    section_id = _section_id(store)
    room = FakeRoom()
    tutor = make_tutor(room)

    def boom(key):
        raise OSError("package files vanished")

    monkeypatch.setattr("open_tutor.agent.load_visible_image_feedback", boom)
    update = AsyncMock()
    monkeypatch.setattr(tutor, "update_chat_ctx", update)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=section_id)
    # Display really succeeded; only the image feedback is missing, and the
    # note says exactly that instead of turning the show into a failure.
    assert result != MATERIAL_SHOW_NOT_SHOWN
    assert "could not be attached" in result and "cannot read them" in result
    assert "do not claim you read them" in result
    assert "Visible intro words." in result
    update.assert_not_awaited()
    assert tutor.mode == "talking"
    assert len(room.local_participant.calls) == 1


async def test_context_update_failure_after_display_is_truthful(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    room = FakeRoom()
    tutor = make_tutor(room)
    update = AsyncMock(side_effect=RuntimeError("context unavailable"))
    monkeypatch.setattr(tutor, "update_chat_ctx", update)
    seen = AsyncMock()
    monkeypatch.setattr(tutor, "add_material_seen", seen)
    result = await tutor.show_material(AsyncMock(), section_id=_section_id(store))
    assert "Visible intro words." in result
    assert "could not be attached" in result and "cannot read them" in result
    seen.assert_awaited_once()  # the shown page still logs its display note
    update.assert_awaited_once()


async def test_ack_gates_image_work(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    calls: list[str] = []

    def spy(key):
        calls.append(key)
        raise AssertionError("an unacked page must not read image files")

    monkeypatch.setattr("open_tutor.agent.load_visible_image_feedback", spy)
    tutor = make_tutor(FakeRoom(error=TimeoutError("no reply")))
    update = AsyncMock()
    monkeypatch.setattr(tutor, "update_chat_ctx", update)
    monkeypatch.setattr(tutor, "add_material_seen", AsyncMock())
    result = await tutor.show_material(AsyncMock(), section_id=_section_id(store))
    assert result == MATERIAL_SHOW_NOT_SHOWN
    assert calls == []
    update.assert_not_awaited()


def test_note_reports_attached_and_omitted_images_without_claiming_all_read():
    meta = {
        "title": "A simple circuit",
        "heading": "A simple circuit",
        "attribution": "Siyavula — Tiny — A simple circuit — CC-BY — siyavula.com",
        "book": {"id": "tiny-book", "title": "Tiny"},
        "visible_text": "Visible intro words.",
        "visible_image_count": 20,
        "completeness": {"text_complete": False},
    }
    note = _material_seen_note(
        "b4", "sec-aaaaaaaaaaaaaaaa", meta, {"attached": 6, "omitted": 14}
    )
    assert "6 original source image(s)" in note
    assert "attached in page order (1-6)" in note
    assert "14 more visible image(s) were left out" in note
    assert "do not claim the whole example" in note
    assert "not a screenshot" in note and "current viewport" in note
    assert note.count("attached in page order") == 1
    assert "cannot read" not in note  # attached images are readable


def test_note_with_every_image_attached_is_explicit():
    meta = {
        "title": "Worked example",
        "heading": "Worked example",
        "attribution": "Siyavula — Tiny — Worked example — CC-BY — siyavula.com",
        "book": {"id": "tiny-book", "title": "Tiny"},
        "visible_text": "Visible words.",
        "visible_image_count": 2,
        "completeness": {"text_complete": False},
    }
    note = _material_seen_note(
        "b5", "sec-aaaaaaaaaaaaaaaa", meta, {"attached": 2, "omitted": 0}
    )
    assert "2 original source image(s)" in note
    assert "Every visible image in this section was attached." in note
    assert "left out" not in note


async def test_string_false_ack_is_not_success(monkeypatch, tmp_path):
    store = _synthetic_store(tmp_path)
    _patch_store(monkeypatch, store)
    room = FakeRoom()
    room.local_participant.perform_rpc = AsyncMock(return_value='{"ok":"false"}')
    tutor = make_tutor(room)
    seen = AsyncMock()
    monkeypatch.setattr(tutor, 'add_material_seen', seen)
    result = await tutor.show_material(AsyncMock(), section_id=_section_id(store))
    assert result == MATERIAL_SHOW_NOT_SHOWN
    seen.assert_not_awaited()
