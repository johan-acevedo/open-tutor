"""Pad each band's companion poses onto one common transparent canvas.

Every pose WebP in web/public/character/{,middle/,upper/} is cropped to the
character, scaled so the character has the band's median height, and placed
bottom-centre on its band's common canvas, then re-exported as WebP
(quality 85, alpha kept). After this, all poses within a band have
identical pixel dimensions, so the avatar <img> (object-fit: contain in
a fixed box) renders every pose at exactly the same scale and position.

Run from the repo root: python3 scripts/normalize_companion_poses.py
Reproducible (run it on the original exports; a rerun only re-encodes): same inputs always give byte-identical
outputs for a given Pillow version (no timestamps are stored in the
files; canvas size derives only from the input dimensions).

After a re-export, bump POSE_VERSION in web/src/bands.ts so caches fetch
the new files.

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


ALPHA_SOLID = 40  # alpha above this counts as the character (ignores soft shadow haze)
MARGIN_TOP = 8    # px of air above the tallest pose


def character_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the visible character (alpha above ALPHA_SOLID)."""
    mask = image.getchannel("A").point(lambda a: 255 if a > ALPHA_SOLID else 0)
    box = mask.getbbox()
    return box if box else (0, 0, image.width, image.height)


def main() -> None:
    for band, directory in BANDS.items():
        files = [(pose, directory / f"{pose}.webp") for pose in POSES]
        missing = [str(path) for _, path in files if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Band {band!r} is missing poses: {missing}")
        crops = []
        for pose, path in files:
            image = Image.open(path)
            image.load()
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            crops.append((pose, path, image.crop(character_box(image))))
        # Scale every pose so the character is the band's median height: the
        # source poses were drawn at different scales (the fox's working pose
        # fills its file, the others do not), and padding alone would make the
        # companion grow and shrink between poses.
        heights = sorted(crop.height for _, _, crop in crops)
        target_h = heights[len(heights) // 2]
        scaled = []
        for pose, path, crop in crops:
            if crop.height != target_h:
                width = max(1, round(crop.width * target_h / crop.height))
                crop = crop.resize((width, target_h), Image.LANCZOS)
            scaled.append((pose, path, crop))
        canvas = (max(crop.width for _, _, crop in scaled), target_h + MARGIN_TOP)
        for pose, path, crop in scaled:
            normalized = Image.new("RGBA", canvas, (0, 0, 0, 0))
            normalized.paste(crop, ((canvas[0] - crop.width) // 2, canvas[1] - crop.height), crop)
            normalized.save(path, "WEBP", quality=85, method=6)
        print(f"Band {band}: canvas {canvas[0]}x{canvas[1]}, character height {target_h}.")


if __name__ == "__main__":
    main()
