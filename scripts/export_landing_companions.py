"""Export the landing page companion images.

For each age band this writes two files under web/public/character/:
- hero.webp: the full companion figure shown beside the landing headline.
  Middle and upper come from the design sources
  (design/bands/{middle,upper}/poses/greeting.png) at native resolution,
  exported as WebP (quality 85, alpha kept).
- face.webp: a 96x96 head crop used as the round face next to band
  cross-link names. The crop boxes below were chosen by looking at the
  artwork: ears and the full face are visible in every band.

Primary hero: the higher-resolution fox chosen by Johan on 2026-11-24
(design/character/hires/greeting-candidate-1.png, see that folder's README).
It is narrower than the in-call greeting.webp, so it is padded to the same
aspect ratio (the page keeps its layout) and scaled to PRIMARY_WIDTH, enough
for a ~460 CSS px hero on 2x screens.

Run from the repo root: python3 scripts/export_landing_companions.py

Reproducible: same inputs always give byte-identical outputs (Pillow
stores no timestamps in WebP). After re-exporting, bump
LANDING_IMG_VERSION in web/src/bands.ts so caches fetch the new files.

Never modifies the existing pose WebP files or
scripts/normalize_companion_poses.py — those serve the in-call avatar.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CHARACTER = ROOT / "web" / "public" / "character"

PRIMARY_SOURCE = ROOT / "design" / "character" / "hires" / "greeting-candidate-1.png"
# Same width:height as the in-call greeting.webp (486x571), and the export width.
PRIMARY_ASPECT = 486 / 571
PRIMARY_WIDTH = 1000

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
    "primary": (72, 0, 952, 880),
    "middle": (195, 10, 635, 450),
    "upper": (215, 55, 600, 440),
}

FACE_SIZE = 96


def export_hero(band: str) -> None:
    src = HERO_SOURCES[band]
    if not src.is_file():
        raise FileNotFoundError(f"Band {band!r} hero source is missing: {src}")
    dest = HERO_DIRS[band] / "hero.webp"
    image = Image.open(src)
    image.load()
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    if band == "primary":
        width = round(image.height * PRIMARY_ASPECT)
        canvas = Image.new("RGBA", (max(width, image.width), image.height), (0, 0, 0, 0))
        canvas.paste(image, ((canvas.width - image.width) // 2, 0))
        height = round(PRIMARY_WIDTH * canvas.height / canvas.width)
        image = canvas.resize((PRIMARY_WIDTH, height), Image.LANCZOS)
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
