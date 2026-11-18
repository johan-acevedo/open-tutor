"""Reviewed Parallel images, served from our own server instead of remote URLs.

A Parallel result URL is only as safe as its next redirect: approving the
bytes and then shipping the original URL lets a later redirect swap in
unreviewed content. So an accepted Parallel image is stored here, under a
content-addressed, unguessable filename (``<sha256>.<ext>``), and the page
gets ``/api/images/<sha256>.<ext>`` on our own web app instead. Only bytes
that passed the vision review are ever stored; unknown hashes answer 404.

The store is scoped per session (``<session>/images/`` next to ``pages/``),
so approved pictures live and die with the session log. Each directory is
bounded (oldest files are dropped past the cap).
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

ROUTE_PREFIX = "/api/images"

EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MEDIA_TYPES = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

FILENAME_RE = re.compile(r"^[0-9a-f]{64}\.(jpg|png|webp)$")

# Enough for a page's pictures with headroom; oldest goes first when full.
MAX_STORED_IMAGES = 32

_cache: dict[str, Path] = {}


def reviewed_images_dir(pages_dir: Path | str) -> Path:
    """Where one session's approved pictures live (``pages/`` sits next to it)."""
    directory = Path(pages_dir).parent / "images"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory


def store_reviewed_image(directory: Path | str, data: bytes, mime: str) -> str:
    """Store approved bytes; return the immutable filename to serve them under."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    ext = EXTENSIONS.get((mime or "").lower())
    if ext is None:
        raise ValueError(f"Refusing to store: unsupported media type {mime!r}")
    name = hashlib.sha256(bytes(data)).hexdigest() + ext
    path = directory / name
    if not path.is_file():
        tmp = directory / f".{name}.tmp-{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(bytes(data))
            os.replace(tmp, path)
        except BaseException:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
    _drop_oldest(directory)
    _cache.pop(name, None)
    return name


def _drop_oldest(directory: Path) -> None:
    """Keep the directory bounded: oldest files go once past the cap."""
    try:
        files = sorted((p for p in directory.iterdir()
                        if p.is_file() and not p.name.startswith(".")),
                       key=lambda p: p.stat().st_mtime)
    except OSError:
        return
    for stale in files[:max(0, len(files) - MAX_STORED_IMAGES)]:
        try:
            stale.unlink()
        except OSError:
            pass


def sessions_base_dir(env: dict[str, str] | Any) -> Path:
    """The sessions directory both the worker and the web app share.

    Mirrors the debug log's directory choice (``TUTOR_DEBUG_LOG_DIR`` wins),
    so the endpoint finds the same ``<session>/images/`` the worker wrote.
    """
    get = env.get if hasattr(env, "get") else (lambda k, d="": os.environ.get(k, d))
    from .debug_log import default_dir_with_env

    return Path(get("TUTOR_DEBUG_LOG_DIR", "") or default_dir_with_env(env))


def find_reviewed_image(base: Path | str, name: str) -> Path | None:
    """The stored file for ``name``, or None for anything invalid or unknown."""
    if not FILENAME_RE.match(name or ""):
        return None
    hit = _cache.get(name)
    if hit is not None and hit.is_file():
        return hit
    _cache.pop(name, None)
    try:
        matches = sorted(Path(base).glob(f"*/images/{name}"))
    except OSError:
        return None
    for match in matches:
        try:
            if match.is_file() and not match.is_symlink():
                _cache[name] = match
                return match
        except OSError:
            continue
    return None


def media_type_for(name: str) -> str | None:
    """The Content-Type to serve ``name`` with, or None when invalid."""
    if not FILENAME_RE.match(name or ""):
        return None
    return MEDIA_TYPES.get(Path(name).suffix.lower())


def url_for(filename: str) -> str:
    """The page-relative URL an approved image is served under."""
    return f"{ROUTE_PREFIX}/{filename}"


class ReviewedImageStore:
    """One session's approved pictures: content-addressed files plus page URLs."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass

    def save(self, data: bytes, mime: str) -> str:
        """Store approved bytes; return the immutable filename to serve them under."""
        return store_reviewed_image(self.directory, data, mime)

    def url_for(self, filename: str) -> str:
        """The page-relative URL an approved image is served under."""
        return url_for(filename)
