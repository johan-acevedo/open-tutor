"""Bounded original-source image feedback for ``show_material`` (step 4d).

After the browser acknowledges a section display, the tutor needs the page's
actual figures and formula images, not only its words. This module resolves a
small fixed set of *original* image files from the section package that is
already built and validated for display:

- Only image sources inside the visible rendered scope are eligible. The
  audited hidden-subtree policy from :func:`open_tutor.materials.render.visible_scope`
  (teacher's-guide prose and grade 4-6 solution subtrees) is reused, never a
  generic CSS engine.
- Only files listed in the package manifest and served with a known image
  media type are read, through :meth:`SectionPackage.asset_file`, so external
  URLs, escaping paths and non-image payloads are never attached.
- Files are deduplicated in document order and capped by a fixed count,
  per-image size and total byte budget: a formula-heavy section must not
  attach hundreds of equations.

No network access, no external URLs, no image model or provider. Blocking
disk work only; the caller runs it in a worker thread.
"""

from __future__ import annotations

from dataclasses import dataclass

from .render import visible_scope
from . import serving

# Fixed budget: a short sequence of real figures/formulae, small enough to keep
# the tutor context and the provider request bounded.
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class SourceImage:
    """One original image file from the shown section, in page order."""

    package_path: str
    mime: str
    data: bytes
    kind: str = ""


@dataclass(frozen=True)
class ImageFeedback:
    """Attached originals plus how many visible images the budget left out."""

    images: tuple[SourceImage, ...] = ()
    omitted: int = 0
    total_bytes: int = 0

    @property
    def attached(self) -> int:
        return len(self.images)


def load_visible_image_feedback(
    section_id: str,
    *,
    env: dict[str, str] | None = None,
    max_images: int = MAX_IMAGES,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> ImageFeedback:
    """Read the bounded original images of one already shown section. Blocking.

    Reuses the process package store, so a displayed section is not packaged
    twice. Raises :class:`open_tutor.materials.serving.UnknownSection` for bad
    IDs and whatever the store raises when a package cannot be prepared.
    """
    key = serving.normalize_section_id(section_id)
    package = serving.material_store_for_process(env).package(key)
    metadata = package.metadata
    grade = (metadata.get("book") or {}).get("grade")
    page = (package.root / "index.html").read_text(encoding="utf-8")
    _, visible_sources = visible_scope(page, hide_solutions=grade in {4, 5, 6})

    entries: dict[str, dict] = {}
    for entry in metadata.get("images", []):
        src = str(entry.get("src") or "")
        if src and src not in entries:
            entries[src] = entry

    ordered: list[dict] = []
    seen: set[str] = set()
    for src in visible_sources:
        entry = entries.get(src)
        if entry is None:
            continue
        path = str(entry.get("package_path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        ordered.append(entry)

    images: list[SourceImage] = []
    total = 0
    omitted = 0
    for entry in ordered:
        path = str(entry["package_path"])
        mime = package.assets.get(path) or ""
        if not mime.startswith("image/") or len(images) >= max_images:
            omitted += 1
            continue
        resolved = package.asset_file(path)
        if resolved is None:
            omitted += 1
            continue
        size = resolved.stat().st_size
        if size <= 0 or size > max_image_bytes or total + size > max_total_bytes:
            omitted += 1
            continue
        data = resolved.read_bytes()
        if len(data) != size or not data:  # short or empty read: never attach
            omitted += 1
            continue
        images.append(
            SourceImage(
                package_path=path,
                mime=mime,
                data=data,
                kind=str(entry.get("kind") or ""),
            )
        )
        total += len(data)
    return ImageFeedback(images=tuple(images), omitted=omitted, total_bytes=total)
