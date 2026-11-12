"""Read-only HTTP serving for original-section packages (material-library step 3b).

One section ID resolves to the exact original EPUB section: a JSON metadata
record and the packaged original page with only its packaged images/CSS.
Packages are produced by :mod:`open_tutor.materials.render` (step 3a) into a
private cache directory outside Git, then published atomically.

Design notes:

- The catalogue resolver is a lazily created process singleton: the eight
  EPUBs are enumerated once, not per request.
- Each section is rendered once per process and per cache version. The build
  happens in a fresh private temp directory inside the cache root, is
  validated, gets a ``.complete`` marker, and is then renamed into place in
  one atomic step, so a half-written package is never served.
- Concurrent requests for the same section ID serialise on a per-ID lock; a
  different section ID builds in parallel.
- Stale packages from an older exporter cannot be served: the cache directory
  name carries the package schema and this module's ``PACKAGE_VERSION``, and a
  hit without a matching ``.complete`` marker and readable metadata is rebuilt.
- Nothing here trusts request input as a path: only the exact relative paths
  listed in the package manifest are served, each resolved inside the package
  root. Unknown IDs are 404, a missing corpus is a clear 503.
- The document is served with ``default-src 'none'``-style CSP (no scripts, no
  forms, no objects, no base) plus ``nosniff``. Because a later
  ``<iframe sandbox>`` frame has an opaque origin, the page's own assets are
  allowed both by ``'self'`` and by an explicit ``scheme://host`` source built
  from the request host, never by a bare scheme. Packaged CSS comes from that
  origin; the wrapper's inline ``<style>`` is allowed by SHA-256 hash only.

Standard library plus FastAPI. No network access, no embeddings, no torch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import base64
import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .catalogue import DEFAULT_BOOKS_PATH, default_data_dir
from .render import PACKAGE_SCHEMA, SectionResolver, export_package, validate_package

# Bump when serving-visible renderer behaviour changes: cache directories carry
# this version, so old packages are never reused after an upgrade.
PACKAGE_VERSION = "1"

COMPLETE_MARKER = ".complete"

SECTION_ID_RE = re.compile(r"^sec-[0-9a-f]{16}$")

# Only these asset types are ever served, with an explicit media type. Anything
# else in a package stays unreachable over HTTP.
MEDIA_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.IGNORECASE | re.DOTALL)

# A host header is echoed into the CSP source list, so it must look like a host
# (optionally with port, or a bracketed IPv6 literal) and nothing else.
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$")

METADATA_CACHE_CONTROL = "no-store"
PAGE_CACHE_CONTROL = "private, max-age=3600"
ASSET_CACHE_CONTROL = "private, max-age=3600"


class UnknownSection(LookupError):
    """Section ID is malformed or absent from the catalogue."""


class CorpusUnavailable(RuntimeError):
    """The pinned EPUB corpus (or its books.json) is not present on this machine."""


class PackageUnavailable(RuntimeError):
    """A known section could not be packaged from the pinned book."""


def default_cache_root() -> Path:
    """Package cache root, honouring XDG. Never inside the Git checkout."""
    base = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
    return Path(base) / "open-tutor" / "material-packages"


def normalize_section_id(value: str) -> str:
    """Return a canonical section ID or raise :class:`UnknownSection`."""
    candidate = (value or "").strip()
    if not SECTION_ID_RE.match(candidate):
        raise UnknownSection(f"Malformed section ID: {value!r}")
    return candidate


def _inline_style_hashes(index_html: str) -> list[str]:
    """SHA-256 hashes of the package page's inline style blocks, for CSP."""
    hashes: list[str] = []
    for match in _STYLE_BLOCK_RE.finditer(index_html):
        digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
        hashes.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return hashes


def _media_type(rel_path: str) -> str | None:
    return MEDIA_TYPES.get(posixpath.splitext(rel_path)[1].lower())


@dataclass
class SectionPackage:
    """One published, validated package on disk."""

    section_id: str
    root: Path
    metadata: dict[str, Any]
    assets: dict[str, str] = field(default_factory=dict)  # package path -> media type
    style_hashes: list[str] = field(default_factory=list)

    def asset_file(self, rel_path: str) -> Path | None:
        """Resolve one allowlisted asset, refusing anything outside the root."""
        if not rel_path or rel_path.startswith(('/', '\\')) or '\\' in rel_path:
            return None
        if '..' in rel_path.split('/') or self.assets.get(rel_path) is None:
            return None
        candidate = (self.root / Path(*Path(rel_path).parts)).resolve()
        if not candidate.is_relative_to(self.root.resolve()) or not candidate.is_file():
            return None
        return candidate


class SectionPackageStore:
    """Lazily initialised, thread-safe store of rendered section packages."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        books_path: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.books_path = Path(books_path) if books_path is not None else None
        self.cache_root = Path(cache_root) if cache_root is not None else None
        self._resolver: SectionResolver | None = None
        self._resolver_lock = threading.Lock()
        self._packages: dict[str, SectionPackage] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "SectionPackageStore":
        """Build a store from optional environment overrides."""
        return cls(
            data_dir=Path(env["TUTOR_MATERIALS_DIR"]) if env.get("TUTOR_MATERIALS_DIR") else None,
            books_path=Path(env["TUTOR_MATERIALS_BOOKS"]) if env.get("TUTOR_MATERIALS_BOOKS") else None,
            cache_root=Path(env["TUTOR_MATERIAL_CACHE"]) if env.get("TUTOR_MATERIAL_CACHE") else None,
        )

    # -- resolver -------------------------------------------------------

    def resolver(self) -> SectionResolver:
        """The process-wide catalogue resolver, built once on first use."""
        with self._resolver_lock:
            if self._resolver is not None:
                return self._resolver
            try:
                self._resolver = SectionResolver(
                    data_dir=self.data_dir if self.data_dir is not None else default_data_dir(),
                    books_path=self.books_path if self.books_path is not None else DEFAULT_BOOKS_PATH,
                )
            except (OSError, ValueError, KeyError) as error:
                raise CorpusUnavailable(str(error)) from error
            return self._resolver

    # -- package build --------------------------------------------------

    def _cache_root(self) -> Path:
        root = self.cache_root if self.cache_root is not None else default_cache_root()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _cache_dir(self, section_id: str) -> Path:
        return self._cache_root() / f"{section_id}--{PACKAGE_SCHEMA.replace('/', '-')}--v{PACKAGE_VERSION}"

    def package(self, section_id: str) -> SectionPackage:
        """Return the cached package for an ID, building it if needed."""
        key = normalize_section_id(section_id)
        cached = self._packages.get(key)
        if cached is not None:
            return cached
        with self._lock:
            id_lock = self._locks.setdefault(key, threading.Lock())
        with id_lock:
            cached = self._packages.get(key)
            if cached is not None:
                return cached
            package = self._build(key)
            with self._lock:
                self._packages[key] = package
            return package

    def _build(self, section_id: str) -> SectionPackage:
        resolver = self.resolver()
        if section_id not in resolver.sections:
            raise UnknownSection(f"Unknown section ID: {section_id}")
        target = self._cache_dir(section_id)
        cached = self._load_published(target, section_id)
        if cached is not None:
            return cached
        return self._export(resolver, section_id, target)

    def _load_published(self, target: Path, section_id: str) -> SectionPackage | None:
        """Read an existing package only when it is complete and consistent."""
        marker = target / COMPLETE_MARKER
        metadata_file = target / "metadata.json"
        if not (marker.is_file() and metadata_file.is_file()):
            return None
        try:
            if marker.read_text(encoding="utf-8").strip() != PACKAGE_VERSION:
                return None
            metadata = _read_metadata(metadata_file)
        except (OSError, ValueError):
            return None
        if metadata.get("section_id") != section_id or metadata.get("schema") != PACKAGE_SCHEMA:
            return None
        index = target / "index.html"
        if not index.is_file():
            return None
        errors = validate_package(target, metadata)
        if errors:
            return None
        try:
            index_html = index.read_text(encoding="utf-8")
        except OSError:
            return None
        return _package_from_metadata(section_id, target, metadata, index_html)

    def _export(self, resolver: SectionResolver, section_id: str, target: Path) -> SectionPackage:
        # Stale or partial leftovers for this version must not survive a rebuild.
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        staging = Path(tempfile.mkdtemp(prefix=f".build-{section_id}-", dir=str(target.parent)))
        try:
            try:
                metadata = export_package(resolver, section_id, staging)
            except (OSError, ValueError, KeyError, FileNotFoundError) as error:
                raise PackageUnavailable(f"Cannot package {section_id}: {error}") from error
            errors = validate_package(staging, metadata)
            if errors:
                raise PackageUnavailable(
                    f"Package validation failed for {section_id}: {'; '.join(errors)}"
                )
            (staging / COMPLETE_MARKER).write_text(PACKAGE_VERSION + "\n", encoding="utf-8")
            try:
                staging.rename(target)
            except OSError:
                # Another process published first, or a leftover appeared.
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                    staging.rename(target)
                else:
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        index_html = (target / "index.html").read_text(encoding="utf-8")
        return _package_from_metadata(section_id, target, metadata, index_html)


def _read_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("metadata.json is not an object")
    return data


def _package_from_metadata(
    section_id: str, root: Path, metadata: dict[str, Any], index_html: str
) -> SectionPackage:
    assets: dict[str, str] = {}
    for entry in metadata.get("files", []):
        path = str(entry.get("path", ""))
        if not path or path in {"index.html", "metadata.json"}:
            continue
        media_type = _media_type(path)
        if media_type is None:
            continue
        assets[path] = media_type
    return SectionPackage(
        section_id=section_id,
        root=root,
        metadata=metadata,
        assets=assets,
        style_hashes=_inline_style_hashes(index_html),
    )


# -- response shaping ---------------------------------------------------


def section_metadata(package: SectionPackage, display_url: str) -> dict[str, Any]:
    """Curated metadata for the tutor: visible content only, no archival text.

    ``owned_text`` stays in the on-disk ``metadata.json`` as archival
    provenance. It describes only the selected section, while the page also
    shows descendants, so it is never presented as visible content here.
    """
    meta = package.metadata
    book = dict(meta.get("book") or {})
    page_dir = display_url.rsplit("/", 1)[0]

    def asset_url(rel_path: str) -> str:
        return f"{page_dir}/{rel_path}" if rel_path else ""

    images = [
        {
            "src": image.get("src", ""),
            "alt": image.get("alt", ""),
            "kind": image.get("kind", ""),
            "resolved": bool(image.get("resolved")),
            "url": asset_url(image.get("package_path") or ""),
        }
        for image in meta.get("images", [])
    ]
    stylesheets = [
        {"href": sheet.get("href", ""), "url": asset_url(sheet.get("package_path") or "")}
        for sheet in meta.get("stylesheets", [])
        if sheet.get("resolved")
    ]
    attribution = "Siyavula — {book} — {section} — {license} — siyavula.com".format(
        book=book.get("title", ""),
        section=meta.get("title", ""),
        license=meta.get("license", ""),
    )
    return {
        "schema": meta.get("schema", ""),
        "section_id": package.section_id,
        "title": meta.get("title", ""),
        "heading": meta.get("heading", ""),
        "breadcrumbs": list(meta.get("breadcrumbs") or []),
        "descendants": list(meta.get("descendants") or []),
        "book": {
            "id": book.get("id", ""),
            "title": book.get("title", ""),
            "grade": book.get("grade"),
            "language": book.get("language", ""),
            "sha256": book.get("sha256", ""),
        },
        "source": {
            "document_href": meta.get("document_href", ""),
            "fragment": meta.get("fragment", ""),
            "source_href": meta.get("source_href", ""),
            "source_url": meta.get("source_url", ""),
            "license_url": meta.get("license_url", ""),
            "target_found": bool(meta.get("target_found")),
            "heading_mismatch": bool(meta.get("heading_mismatch")),
        },
        "license": {
            "name": meta.get("license", ""),
            "url": meta.get("license_url", ""),
            "evidence": list(meta.get("license_evidence") or []),
        },
        "attribution": attribution,
        "display_url": display_url,
        "visible_text": meta.get("visible_text", ""),
        "visible_image_count": int(meta.get("visible_image_count") or 0),
        "completeness": {
            "text_complete": bool(meta.get("text_complete")),
            "visible_image_count": int(meta.get("visible_image_count") or 0),
            "feedback_policy": meta.get("feedback_policy", ""),
            "note": (
                "Visible scope includes descendant subsections; hidden source "
                "teacher/solution prose is excluded. Math may live in images."
            ),
        },
        "images": images,
        "stylesheets": stylesheets,
    }


def _csp_sources(request: Request) -> list[str]:
    """Asset origins that work in an opaque-origin sandboxed frame.

    ``'self'`` is kept (Chromium matches it inside a sandboxed frame), but a
    sandboxed frame has an opaque origin, so the exact ``scheme://host`` of this
    response is allowed as well. Only a host-shaped ``Host`` header is echoed.
    """
    sources = ["'self'"]
    host = request.headers.get("host", "")
    if _HOST_RE.match(host):
        sources.extend([f"http://{host}", f"https://{host}"])
    return sources


def content_security_policy(request: Request, style_hashes: list[str] | None = None) -> str:
    """Restrictive CSP for a material page or asset: no script, no frame-out."""
    sources = _csp_sources(request)
    styles = ["'self'"] + [source for source in sources if source != "'self'"]
    if style_hashes:
        styles.extend(style_hashes)
    directives = [
        "default-src 'none'",
        "script-src 'none'",
        "style-src " + " ".join(styles),
        "img-src " + " ".join(sources),
        "base-uri 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "frame-ancestors 'self'",
    ]
    return "; ".join(directives)


def material_headers(request: Request, *, style_hashes: list[str] | None = None) -> dict[str, str]:
    """Headers applied to every material response."""
    return {
        "Content-Security-Policy": content_security_policy(request, style_hashes),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        # A sandboxed frame has an opaque origin, so CORP ``same-origin`` blocks
        # the page's own CSS and images (Chromium: ERR_BLOCKED_BY_RESPONSE.
        # NotSameOrigin). These responses exist to be embedded, and the material
        # is public CC-BY content, so they are deliberately embeddable.
        "Cross-Origin-Resource-Policy": "cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    }


# -- routes -------------------------------------------------------------


def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


def materials_router(store: SectionPackageStore) -> APIRouter:
    """Read-only routes for one section package and its allowlisted assets."""
    router = APIRouter()

    async def _package(section_id: str) -> SectionPackage | JSONResponse:
        try:
            return await run_in_threadpool(store.package, section_id)
        except UnknownSection:
            return _error(404, f"Unknown section ID: {section_id}")
        except CorpusUnavailable as error:
            return _error(
                503,
                "Material corpus unavailable on this host: "
                f"{error}. Original EPUBs must be downloaded first.",
            )
        except PackageUnavailable as error:
            return _error(500, f"Section package unavailable: {error}")

    @router.get("/api/materials/sections/{section_id}")
    async def section_metadata_route(section_id: str) -> Response:
        package = await _package(section_id)
        if isinstance(package, JSONResponse):
            return package
        display_url = f"/materials/sections/{package.section_id}/index.html"
        return JSONResponse(
            content=section_metadata(package, display_url),
            headers={
                "Cache-Control": METADATA_CACHE_CONTROL,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/materials/sections/{section_id}/index.html")
    async def section_page_route(section_id: str, request: Request) -> Response:
        package = await _package(section_id)
        if isinstance(package, JSONResponse):
            return package
        index = package.root / "index.html"
        return FileResponse(
            index,
            media_type="text/html; charset=utf-8",
            headers={
                **material_headers(request, style_hashes=package.style_hashes),
                "Cache-Control": PAGE_CACHE_CONTROL,
            },
        )

    @router.get("/materials/sections/{section_id}/{asset_path:path}")
    async def section_asset_route(section_id: str, asset_path: str, request: Request) -> Response:
        package = await _package(section_id)
        if isinstance(package, JSONResponse):
            return package
        resolved = await run_in_threadpool(package.asset_file, asset_path)
        if resolved is None:
            return _error(404, "Unknown material asset")
        media_type = package.assets[asset_path]
        return FileResponse(
            resolved,
            media_type=media_type,
            headers={
                **material_headers(request),
                "Cache-Control": ASSET_CACHE_CONTROL,
            },
        )

    return router
