"""Behavioural tests for read-only section serving (step 3b).

Synthetic-EPUB tests pin ID resolution, the metadata contract, the allowlisted
asset routes, CSP/nosniff headers, traversal refusal, concurrency and cache
freshness. Live-corpus tests exercise the real pinned books and skip when the
corpus is absent. No test needs torch or a browser.
"""

import hashlib
import json
from pathlib import Path
import threading
import zipfile

import pytest
from fastapi.testclient import TestClient

from open_tutor.materials.serving import (
    PACKAGE_VERSION,
    CorpusUnavailable,
    SectionPackageStore,
    UnknownSection,
    materials_router,
)
from open_tutor.web import create_app

CORPUS = Path.home() / ".local" / "share" / "open-tutor" / "materials" / "siyavula"
BOOKS_JSON = Path(__file__).resolve().parents[2] / "tools" / "siyavula" / "books.json"

GRADE6_CIRCUIT_ID = "sec-ecd16baf9e4fee44"  # A simple circuit
MATHS10_SUBSTITUTION_ID = "sec-6a9c825e9c3f2cd2"  # Solving by substitution
MATHS10_PARENT_ID = "sec-83e2150c0737cec5"  # parent scope with math descendants

needs_corpus = pytest.mark.skipif(
    not (CORPUS / "Gr6_NaturalSciences_Learner_Eng_CC-BY.epub").exists()
    or not (CORPUS / "Gr10_Mathematics_Learner_Eng_CC-BY.epub").exists()
    or not BOOKS_JSON.exists(),
    reason="downloaded Siyavula corpus is not present",
)


def _png(seed: bytes) -> bytes:
    return hashlib.sha256(seed).digest() * 4


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


NAV = (
    '<li><a href="ch.xhtml#top">Top</a><ol>'
    '<li><a href="ch.xhtml#sub">Sub</a></li>'
    '<li><a href="ch.xhtml#broken">Broken</a></li></ol></li>'
)
DOC = (
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>c</title>'
    '<link rel="stylesheet" type="text/css" href="a.css"/></head><body>'
    '<div class="section"><h1 id="top">Top</h1><p>Visible intro.</p>'
    '<div class="teachers-guide"><p>Teacher secret.</p></div>'
    '<img class="math-block" src="equation/e1.png" alt=""/>'
    '<img src="images/photo.jpg" alt="photo"/>'
    '<div class="section"><h2 id="sub">Sub heading</h2><p>Child body.</p>'
    '<img class="math-inline" src="equation/e2.png" alt=""/></div>'
    "</div>"
    '<div class="section"><h2 id="broken">Broken</h2>'
    '<p>Broken body.</p><img src="equation/e3.png" srcset="https://example.com/e3.png 2x"/></div>'
    "</body></html>"
)
ASSETS = {
    "a.css": b".math-block{}\n",
    "images/photo.jpg": b"\xff\xd8\xff\xe0JFIF\x00" + hashlib.sha256(b"photo").digest() * 4,
    "equation/e1.png": _png(b"e1"),
    "equation/e2.png": _png(b"e2"),
    "equation/e3.png": _png(b"e3"),
}


def _store(tmp_path: Path) -> SectionPackageStore:
    corpus = tmp_path / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    _write_epub(corpus / "tiny.epub", NAV, {"ch.xhtml": DOC}, ASSETS)
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


def _client(store: SectionPackageStore) -> TestClient:
    return TestClient(create_app({}, materials_store=store))


def _id(store: SectionPackageStore, title: str) -> str:
    return next(section.id for section in store.resolver().sections.values() if section.title == title)


def test_metadata_route_describes_visible_content_only(tmp_path):
    store = _store(tmp_path)
    client = _client(store)
    section_id = _id(store, "Top")
    response = client.get(f"/api/materials/sections/{section_id}")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    body = response.json()
    assert body["section_id"] == section_id
    assert body["title"] == "Top"
    # Descendants are inside the visible scope; hidden teacher prose is not.
    assert "Visible intro." in body["visible_text"]
    assert "Child body." in body["visible_text"]
    assert "Teacher secret." not in body["visible_text"]
    assert "owned_text" not in body
    assert body["visible_image_count"] == 3
    assert body["completeness"]["text_complete"] is False
    assert body["book"]["id"] == "tiny-book" and body["book"]["grade"] == 6
    assert body["source"]["document_href"] == "text/ch.xhtml"
    assert body["license"]["name"] == "CC-BY"
    assert body["license"]["url"].startswith("https://creativecommons.org/")
    assert body["display_url"] == f"/materials/sections/{section_id}/index.html"
    assert [image["url"] for image in body["images"] if image["resolved"]]
    assert body["attribution"].startswith("Siyavula — Tiny —")


def test_page_and_assets_served_with_strict_csp(tmp_path):
    store = _store(tmp_path)
    client = _client(store)
    section_id = _id(store, "Top")
    page = client.get(f"/materials/sections/{section_id}/index.html")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    csp = page.headers["content-security-policy"]
    for directive in (
        "default-src 'none'",
        "script-src 'none'",
        "base-uri 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
    ):
        assert directive in csp
    assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
    # Opaque-origin sandbox support: assets are allowed by 'self' and by the
    # concrete scheme://host, never by a bare scheme.
    assert "img-src 'self' http://testserver https://testserver" in csp
    assert "data:" not in csp and "https:;" not in csp
    # The wrapper's inline style is allowed by its exact SHA-256 hash.
    style = page.text.split("<style>", 1)[1].split("</style>", 1)[0]
    digest = hashlib.sha256(style.encode("utf-8")).digest()
    import base64

    assert "'sha256-" + base64.b64encode(digest).decode("ascii") + "'" in csp
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["referrer-policy"] == "no-referrer"
    # Embeddable by design: an opaque-origin sandboxed frame cannot load
    # CORP= same-origin assets from its own page.
    assert page.headers["cross-origin-resource-policy"] == "cross-origin"
    # Original page content, including the hidden teacher subtree in markup.
    assert "Visible intro." in page.text and "Child body." in page.text
    assert "Teacher secret." in page.text  # markup keeps source; feedback excludes it

    css = client.get(f"/materials/sections/{section_id}/a.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert css.text.startswith(".math-block")
    png = client.get(f"/materials/sections/{section_id}/equation/e1.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content == ASSETS["equation/e1.png"]
    assert png.headers["x-content-type-options"] == "nosniff"
    assert png.headers["cross-origin-resource-policy"] == "cross-origin"
    jpeg = client.get(f"/materials/sections/{section_id}/images/photo.jpg")
    assert jpeg.status_code == 200 and jpeg.headers["content-type"] == "image/jpeg"
    assert jpeg.content == ASSETS["images/photo.jpg"]


@pytest.mark.parametrize(
    "asset_path",
    [
        "metadata.json",
        "../metadata.json",
        "%2e%2e/metadata.json",
        "..%2f..%2fetc%2fpasswd",
        "equation/missing.png",
        "equation",
        "a.css%00.png",
    ],
)
def test_asset_allowlist_refuses_everything_else(tmp_path, asset_path):
    store = _store(tmp_path)
    client = _client(store)
    section_id = _id(store, "Top")
    assert client.get(f"/materials/sections/{section_id}/{asset_path}").status_code == 404


def test_unknown_ids_404_without_guessing(tmp_path):
    store = _store(tmp_path)
    client = _client(store)
    for section_id in ("sec-0000000000000000", "not-an-id", "sec-0123456789ABCDEF"):
        assert client.get(f"/api/materials/sections/{section_id}").status_code == 404
        assert client.get(f"/materials/sections/{section_id}/index.html").status_code == 404


def test_missing_corpus_is_a_clear_unavailable_response(tmp_path):
    store = SectionPackageStore(
        data_dir=tmp_path / "absent-corpus",
        books_path=BOOKS_JSON,
        cache_root=tmp_path / "cache",
    )
    client = _client(store)
    response = client.get("/api/materials/sections/sec-0123456789abcdef")
    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()
    # A default app (no corpus injection, no torch) still imports and serves health.
    assert TestClient(create_app({})).get("/api/health").status_code == 200


def test_unpackageable_section_reports_failure(tmp_path):
    store = _store(tmp_path)
    client = _client(store)
    section_id = _id(store, "Broken")
    response = client.get(f"/api/materials/sections/{section_id}")
    assert response.status_code == 500
    assert "unavailable" in response.json()["detail"].lower()


def test_concurrent_requests_build_one_package(tmp_path, monkeypatch):
    store = _store(tmp_path)
    section_id = _id(store, "Top")
    calls: list[str] = []
    original = SectionPackageStore._export
    lock = threading.Lock()

    def counting(self, resolver, key, target):
        with lock:
            calls.append(key)
        return original(self, resolver, key, target)

    monkeypatch.setattr(SectionPackageStore, "_export", counting)
    results: list[object] = []
    errors: list[BaseException] = []

    def fetch():
        try:
            results.append(store.package(section_id))
        except BaseException as error:  # noqa: BLE001 - surfaced below
            errors.append(error)

    threads = [threading.Thread(target=fetch) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    assert calls == [section_id]
    assert len({package.root for package in results}) == 1
    assert (results[0].root / "index.html").is_file()


def test_incomplete_or_stale_cache_is_rebuilt(tmp_path):
    store = _store(tmp_path)
    section_id = _id(store, "Top")
    package = store.package(section_id)
    cache_dir = package.root
    assert (cache_dir / ".complete").read_text(encoding="utf-8").strip() == PACKAGE_VERSION

    # A cache entry without its completion marker is never served.
    (cache_dir / ".complete").unlink()
    fresh = SectionPackageStore(
        data_dir=tmp_path / "corpus",
        books_path=tmp_path / "books.json",
        cache_root=tmp_path / "cache",
    )
    rebuilt = fresh.package(section_id)
    assert (rebuilt.root / ".complete").is_file()
    assert (rebuilt.root / "index.html").is_file()

    # Corrupt metadata for the current version is rebuilt rather than served.
    (rebuilt.root / "metadata.json").write_text("{not json", encoding="utf-8")
    (rebuilt.root / ".complete").unlink()
    again = SectionPackageStore(
        data_dir=tmp_path / "corpus",
        books_path=tmp_path / "books.json",
        cache_root=tmp_path / "cache",
    )
    assert json.loads((again.package(section_id).root / "metadata.json").read_text())["section_id"] == section_id


def test_cache_lives_outside_the_checkout(tmp_path):
    store = _store(tmp_path)
    package = store.package(_id(store, "Top"))
    assert (tmp_path / "cache") in package.root.parents


@needs_corpus
def test_real_grade6_circuit_serves_original_section(tmp_path):
    store = SectionPackageStore(cache_root=tmp_path / "cache")
    client = _client(store)
    meta = client.get(f"/api/materials/sections/{GRADE6_CIRCUIT_ID}")
    assert meta.status_code == 200
    body = meta.json()
    assert body["title"] == "A simple circuit"
    # Parent fix: hidden teacher-guide prose must not reach tutor feedback.
    assert "Many misconceptions develop" in (store.package(GRADE6_CIRCUIT_ID).root / "index.html").read_text()
    assert "Many misconceptions develop" not in body["visible_text"]
    assert "Circuit components" in body["visible_text"]  # visible descendant included
    assert body["book"]["grade"] == 6
    assert body["license"]["evidence"]
    assert body["images"] and all(image["resolved"] for image in body["images"])
    page = client.get(body["display_url"])
    assert page.status_code == 200 and "Circuit components" in page.text
    image_url = next(image["url"] for image in body["images"] if image["kind"] == "image")
    image = client.get(image_url)
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/")
    css_url = body["stylesheets"][0]["url"]
    css = client.get(css_url)
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


@needs_corpus
def test_real_maths_substitution_keeps_equation_images(tmp_path):
    store = SectionPackageStore(cache_root=tmp_path / "cache")
    client = _client(store)
    body = client.get(f"/api/materials/sections/{MATHS10_SUBSTITUTION_ID}").json()
    assert body["title"] == "Solving by substitution"
    assert "Worked example 6" in body["visible_text"]
    maths_images = [image for image in body["images"] if image["kind"].startswith("math")]
    assert len(maths_images) == 29
    assert all(image["resolved"] and image["url"] for image in maths_images)
    assert body["completeness"]["text_complete"] is False
    sample = client.get(maths_images[0]["url"])
    assert sample.status_code == 200 and sample.headers["content-type"] == "image/png"


@needs_corpus
def test_real_parent_section_feedback_is_image_complete(tmp_path):
    store = SectionPackageStore(cache_root=tmp_path / "cache")
    client = _client(store)
    body = client.get(f"/api/materials/sections/{MATHS10_PARENT_ID}").json()
    assert body["visible_text"] and len(body["visible_text"]) > 1000
    assert body["visible_image_count"] > 100
    assert body["completeness"]["text_complete"] is False
    assert client.get(body["display_url"]).status_code == 200
