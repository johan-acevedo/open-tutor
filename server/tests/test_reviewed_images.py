"""Reviewed Parallel pictures: only approved bytes are served, under an
unguessable content hash, with immutable caching and no sniffing.

Run them with: cd server && uv run pytest -q
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

from open_tutor.reviewed_images import (
    ReviewedImageStore,
    find_reviewed_image,
    media_type_for,
    reviewed_images_dir,
)
from open_tutor.web import create_app

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

ENV = {"LIVEKIT_URL": "wss://example.livekit.cloud", "LIVEKIT_API_KEY": "APIkey", "LIVEKIT_API_SECRET": "s" * 40}


def session_env(tmp_path):
    sessions = tmp_path / "sessions"
    store = ReviewedImageStore(reviewed_images_dir(sessions / "room1" / "pages"))
    name = store.save(JPEG, "image/jpeg")
    png = store.save(PNG, "image/png")
    assert store.url_for(name) == f"/api/images/{name}"
    assert find_reviewed_image(sessions, name).name == name
    return {**ENV, "TUTOR_DEBUG_LOG_DIR": str(sessions)}, name, png


def test_serves_only_reviewed_hashes_with_immutable_cache(tmp_path):
    env, name, png = session_env(tmp_path)
    client = TestClient(create_app(env))
    response = client.get(f"/api/images/{name}")
    assert response.status_code == 200
    assert response.content == JPEG
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/images/{png}").headers["content-type"] == "image/png"


def test_unknown_and_invalid_names_are_404(tmp_path):
    env, name, _ = session_env(tmp_path)
    client = TestClient(create_app(env))
    unknown = "0" * 64 + ".jpg"
    assert unknown != name
    assert client.get(f"/api/images/{unknown}").status_code == 404
    for bad in ("../sessions/x", "abc", name.upper(), name + ".bak",
                name.replace(".jpg", ".svg"), "", "nope.jpg"):
        assert client.get(f"/api/images/{bad}").status_code == 404


def test_files_outside_the_store_are_not_served(tmp_path):
    env, name, _ = session_env(tmp_path)
    sessions = tmp_path / "sessions"
    (sessions / "room1" / "pages").mkdir(parents=True, exist_ok=True)
    (sessions / "room1" / "pages" / (name)).write_bytes(b"planted")
    (sessions / "room1" / (name)).write_bytes(b"planted")
    client = TestClient(create_app(env))
    assert client.get(f"/api/images/{name}").status_code == 200
    assert client.get(f"/api/images/{name}").content == JPEG


def test_store_rejects_unknown_types_and_stays_bounded(tmp_path):
    store = ReviewedImageStore(tmp_path / "images")
    with pytest.raises(ValueError, match="unsupported media type"):
        store.save(b"GIF89a", "image/gif")
    one = store.save(JPEG, "image/jpeg")
    assert store.save(JPEG, "image/jpeg") == one  # content-addressed: same bytes, same name
    assert media_type_for(one) == "image/jpeg"
    assert media_type_for("x.svg") is None


def test_store_evicts_oldest_past_the_cap(tmp_path, monkeypatch):
    import open_tutor.reviewed_images as reviewed

    monkeypatch.setattr(reviewed, "MAX_STORED_IMAGES", 3)
    store = ReviewedImageStore(tmp_path / "images")
    names = [store.save(bytes([i]) * 100, "image/png") for i in range(5)]
    kept = sorted(p.name for p in (tmp_path / "images").iterdir())
    assert kept == sorted(names[2:])
    assert hashlib.sha256(bytes([4]) * 100).hexdigest() + ".png" in kept
