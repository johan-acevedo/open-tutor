"""Export the selected imagegen strips using the existing RGBA WebP pipeline.

Run from any directory: python3 scripts/export_band_companions.py
Only crop, matte-edge cleanup, sizing and encoding happen here. Artwork comes
from the preserved generated PNGs; no poses are synthesized by this script.
"""

import json
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BANDS = ROOT / "design" / "bands"


def main():
    report = []
    for entry in json.loads((BANDS / "export-manifest.json").read_text()):
        source = Image.open(BANDS / entry["band"] / "sources" / entry["file"])
        if source.mode != "RGBA":
            raise ValueError(f"Source has no transparency: {entry}")
        width, height = source.size
        split = width if len(entry["poses"]) == 1 else width // 2
        if len(entry["poses"]) == 1:
            bounds = source.getchannel("A").point(lambda a: 255 if a > 200 else 0).getbbox()
            if not bounds:
                raise ValueError(f"Empty source: {entry}")
            split = min(width, bounds[2] + round(height * 0.04))
        if len(entry["poses"]) == 2:
            columns = source.getchannel("A").point(lambda a: 255 if a > 200 else 0).getprojection()[0]
            gaps = []
            start = None
            for x in range(width // 3, width * 2 // 3):
                if not columns[x] and start is None:
                    start = x
                elif columns[x] and start is not None:
                    gaps.append((start, x))
                    start = None
            if not gaps:
                raise ValueError(f"No transparent gutter between poses: {entry}")
            left, right = max(gaps, key=lambda gap: gap[1] - gap[0])
            split = (left + right) // 2
        for index, pose in enumerate(entry["poses"]):
            image = source.crop((0 if index == 0 else split, 0, split if index == 0 else width, height))
            alpha = image.getchannel("A")
            bounds = alpha.point(lambda a: 255 if a > 200 else 0).getbbox()
            if not bounds or bounds[0] == 0 or bounds[1] == 0 or bounds[2] == image.width:
                raise ValueError(f"Clipped or empty pose: {entry['band']}/{pose}")
            # The fox extractor also erodes the matte by one pixel before export.
            image.putalpha(alpha.filter(ImageFilter.MinFilter(3)))
            if image.height > 900:
                image = image.resize((round(image.width * 900 / image.height), 900), Image.Resampling.LANCZOS)
            png = BANDS / entry["band"] / "poses" / f"{pose}.png"
            webp = ROOT / "web" / "public" / "character" / entry["band"] / f"{pose}.webp"
            png.parent.mkdir(parents=True, exist_ok=True)
            webp.parent.mkdir(parents=True, exist_ok=True)
            image.save(png)
            image.save(webp, "WEBP", quality=88, method=6)
            exported = Image.open(webp)
            assert exported.mode == "RGBA" and exported.getchannel("A").getextrema() == (0, 255)
            report.append({"band": entry["band"], "pose": pose, "size": list(image.size), "bytes": webp.stat().st_size})
    (BANDS / "exports.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Exported {len(report)} transparent PNG/WebP poses. Fox assets untouched.")


if __name__ == "__main__":
    main()
