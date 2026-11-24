#!/usr/bin/env python3
"""Rebuild transparent cut-outs and the review sheet from preserved raw renders.

Run from the repository root:
    uv run --with numpy --with scipy --with pillow python design/character/hires/rebuild.py
"""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKGROUND = (24, 27, 34)
BOTTOM = {1: 1430, 2: 1460, 3: 1460}
NOSES = {0: (257, 230), 1: (517, 600), 2: (516, 616), 3: (518, 580)}


def cut_out(number):
    source = HERE / "raw" / f"greeting-generated-{number}.png"
    rgb = np.asarray(Image.open(source).convert("RGB"), dtype=np.float32)
    excess = rgb[:, :, 1] - np.maximum(rgb[:, :, 0], rgb[:, :, 2])
    sure_bg = (excess > 190) & (rgb[:, :, 1] > 230)
    sure_fg = excess <= 0
    # As in the existing extraction scripts, keep foreground and background
    # seeds distinct. Here chroma green cannot be confused with the navy hoodie.
    bg_indices = ndimage.distance_transform_edt(~sure_bg, return_distances=False,
                                              return_indices=True)
    fg_indices = ndimage.distance_transform_edt(~sure_fg, return_distances=False,
                                              return_indices=True)
    bg = rgb[tuple(bg_indices)]
    fg = rgb[tuple(fg_indices)]
    direction = fg - bg
    alpha = np.clip(np.sum((rgb - bg) * direction, axis=2) /
                    np.maximum(np.sum(direction * direction, axis=2), 1), 0, 1)
    alpha[sure_bg] = 0
    alpha[sure_fg] = 1
    labels, count = ndimage.label(alpha > 0.02)
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    keep = labels == sizes.argmax()
    alpha[~keep] = 0
    # Borrow nearby opaque colour for mixed edges. Inverting the green blend
    # amplifies small matte errors into black specks visible on white.
    color = np.where((excess > 0)[:, :, None], fg, rgb)
    rgba = np.dstack((np.clip(color, 0, 255), alpha * 255)).astype(np.uint8)
    ys, xs = np.nonzero(alpha > .03)
    box = (max(0, int(xs.min()) - 3), max(0, int(ys.min()) - 3),
           min(rgb.shape[1], int(xs.max()) + 4), BOTTOM[number])
    rgba = rgba[box[1]:box[3], box[0]:box[2]].copy()
    fade = round(rgba.shape[0] * .10)
    rgba[-fade:, :, 3] = (rgba[-fade:, :, 3].astype(float) *
                         np.linspace(1, 0, fade)[:, None]).astype(np.uint8)
    # The built-in tool returned 948px-wide images despite the requested size.
    # This small Lanczos resample makes the final width exactly 1024px.
    result = Image.fromarray(rgba)
    result = result.resize((1024, round(result.height * 1024 / result.width)), Image.Resampling.LANCZOS)
    array = np.asarray(result).copy()
    # Resampling can produce a few green edge pixels through ringing.
    array[:, :, 1] = np.minimum(array[:, :, 1], np.maximum(array[:, :, 0], array[:, :, 2]))
    array[array[:, :, 3] == 0, :3] = 0
    result = Image.fromarray(array)
    result.save(HERE / f"greeting-candidate-{number}.png", optimize=True)
    return result, {"raw_size": [rgb.shape[1], rgb.shape[0]], "crop_box": box,
                    "final_size": list(result.size), "raw_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def font(size):
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)


def main():
    current = Image.open(ROOT / "web/public/character/greeting.webp").convert("RGBA")
    images = [current]
    metadata = {}
    for i in range(1, 4):
        image, details = cut_out(i)
        images.append(image)
        metadata[str(i)] = details
    (HERE / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    width, height, gap, display_height = 1040, 2340, 32, 1142
    sheet = Image.new("RGB", (width * 4 + gap * 5, height), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    labels = ["Current · Lanczos reference", "Candidate 1 · rank 1", "Candidate 2 · rank 2", "Candidate 3 · rank 3"]
    for i, (label, image) in enumerate(zip(labels, images)):
        x = gap + i * (width + gap)
        draw.text((x + 16, 36), label, font=font(42), fill=(243, 245, 248))
        draw.text((x + 16, 100), f"{image.width} × {image.height} RGBA", font=font(34), fill=(155, 163, 180))
        display = image.resize((round(image.width * display_height / image.height), display_height), Image.Resampling.LANCZOS)
        sheet.paste(display, (x + (width - display.width) // 2, 176), display)
        draw.text((x + 16, 1360), "Face detail · 2× display pixels", font=font(38), fill=(243, 245, 248))
        nx, ny = NOSES[i]
        if i:
            raw_box = metadata[str(i)]["crop_box"]
            nx = (nx - raw_box[0]) * image.width / (raw_box[2] - raw_box[0])
            ny = (ny - raw_box[1]) * image.height / (raw_box[3] - raw_box[1])
        scale = display_height / image.height
        nx, ny = round(nx * scale), round(ny * scale)
        crop = display.crop((nx - 230, ny - 200, nx + 230, ny + 210))
        crop = crop.resize((920, 820), Image.Resampling.LANCZOS)
        sheet.paste(crop, (x + 60, 1444), crop)
    sheet.save(HERE / "compare.png", optimize=True)
    print(json.dumps(metadata, indent=2))
    print("Saved", HERE / "compare.png")


if __name__ == "__main__":
    main()
