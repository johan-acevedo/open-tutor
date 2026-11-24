"""Export the landing page companion images.

For each age band this writes two files under web/public/character/:
- hero.webp: the full companion figure shown beside the landing headline.
  Middle and upper come from the design sources
  (design/bands/{middle,upper}/poses/greeting.png) at native resolution,
  exported as WebP (quality 85, alpha kept).
- face.webp: a 96x96 head crop used as the round face next to band
  cross-link names. The crop boxes below were chosen by looking at the
  artwork: ears and the full face are visible in every band.

Primary hero: PRIMARY_SOURCE below points at the shipped greeting.webp, so
the script copies it byte-for-byte for now. When the higher-resolution fox
arrives, point PRIMARY_SOURCE at the new file (and adjust FACE_CROPS if
its framing differs) — no other change needed.

Run from the repo root: python3 scripts/export_landing_companions.py

Reproducible: same inputs always give byte-identical outputs (Pillow
stores no timestamps in WebP). After re-exporting, bump
LANDING_IMG_VERSION in web/src/bands.ts so caches fetch the new files.

Never modifies the existing pose WebP files or
scripts/normalize_companion_poses.py — those serve the in-call avatar.
"""

import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CHARACTER = ROOT / "web" / "public" / "character"

# Higher-resolution fox arrives in a later change: point this at it then.
PRIMARY_SOURCE = CHARACTER / "greeting.webp"

HERO_SOURCES = {
    "primary": PRIMARY_SOURCE,
    "middle": ROOT / "design" / "bands" / "middle" / "poses" / "greeting.png",
    "upper": ROOT / "design" / "bands" / "upper" / "poses" / "greeting.png",
}

HERO_DIRS = {
    "primary": CHARACTER,
    "middle": CHARACTER / "middle",
    "upper": CHARACTER / "upper",
}

# Square head crops in each hero source's own pixels (left, top, right, bottom).
FACE_CROPS = {
    "primary": (62, 2, 412, 352),
    "middle": (195, 10, 635, 450),
    "upper": (215, 55, 600, 440),
}

FACE_SIZE = 96


def export_hero(band: str) -> None:
    src = HERO_SOURCES[band]
    if not src.is_file():
        raise FileNotFoundError(f"Band {band!r} hero source is missing: {src}")
    dest = HERO_DIRS[band] / "hero.webp"
    if src == CHARACTER / "greeting.webp":
        # Byte-for-byte copy: re-encoding the shipped WebP would only add
        # generation loss until the hi-res fox arrives.
        shutil.copyfile(src, dest)
        print(f"Band {band}: copied {src.name} -> {dest.relative_to(ROOT)}.")
        return
    image = Image.open(src)
    image.load()
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "WEBP", quality=85, method=6)
    print(f"Band {band}: {src.relative_to(ROOT)} -> {dest.relative_to(ROOT)} ({image.size[0]}x{image.size[1]}).")


def export_face(band: str) -> None:
    src = HERO_SOURCES[band]
    image = Image.open(src)
    image.load()
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    face = image.crop(FACE_CROPS[band]).resize((FACE_SIZE, FACE_SIZE), Image.LANCZOS)
    dest = HERO_DIRS[band] / "face.webp"
    face.save(dest, "WEBP", quality=85, method=6)
    print(f"Band {band}: face -> {dest.relative_to(ROOT)} ({FACE_SIZE}x{FACE_SIZE}).")


def main() -> None:
    for band in ("primary", "middle", "upper"):
        export_hero(band)
        export_face(band)


if __name__ == "__main__":
    main()
