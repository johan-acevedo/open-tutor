"""Pad each band's companion poses onto one common transparent canvas.

Every pose WebP in web/public/character/{,middle/,upper/} is placed,
unscaled, bottom-centre aligned on its band's common canvas
(max width x max height across that band's poses) and re-exported as
WebP (quality 85, alpha kept). After this, all poses within a band have
identical pixel dimensions, so the avatar <img> (object-fit: contain in
a fixed box) renders every pose at exactly the same scale and position.

Run from the repo root: python3 scripts/normalize_companion_poses.py
Idempotent and reproducible: same inputs always give byte-identical
outputs for a given Pillow version (no timestamps are stored in the
files; canvas size derives only from the input dimensions).

Never touches the artwork sources under design/ — only the derived
WebP files served to the page.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CHARACTER = ROOT / "web" / "public" / "character"

# Band name -> directory holding that band's 7 pose WebP files.
BANDS = {
    "primary": CHARACTER,
    "middle": CHARACTER / "middle",
    "upper": CHARACTER / "upper",
}

POSES = ("greeting", "listening", "speaking", "thinking", "working", "waiting", "pointing")


def main() -> None:
    for band, directory in BANDS.items():
        files = [(pose, directory / f"{pose}.webp") for pose in POSES]
        missing = [str(path) for _, path in files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Band {band!r} is missing poses: {missing}")
        images = []
        for pose, path in files:
            image = Image.open(path)
            image.load()
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            images.append((pose, path, image))
        canvas = (max(image.width for _, _, image in images), max(image.height for _, _, image in images))
        for pose, path, image in images:
            if (image.width, image.height) == canvas:
                # Already on the common canvas; re-export anyway so the
                # encoder settings are uniform across the band.
                normalized = image
            else:
                normalized = Image.new("RGBA", canvas, (0, 0, 0, 0))
                normalized.paste(image, ((canvas[0] - image.width) // 2, canvas[1] - image.height), image)
            normalized.save(path, "WEBP", quality=85, method=6)
        print(f"Band {band}: canvas {canvas[0]}x{canvas[1]}, padded {len(images)} poses.")


if __name__ == "__main__":
    main()
