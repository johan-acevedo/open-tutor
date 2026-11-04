"""Clean the cut-out poses: drop thin streaks and finish each bust with a soft fade.

Run after scripts/extract_character.py:  python3 scripts/clean_character.py
Needs Pillow and numpy.
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "web" / "public" / "character"
# Fraction of the height to keep, chosen so the cut lands above the ragged sheet edge.
KEEP = {"listening": 0.86, "speaking": 0.86, "thinking": 0.86, "waiting": 0.90, "greeting": 1.0, "pointing": 1.0}
FADE = 0.10
# Horizontal opening radius: wide enough to remove the thin vertical streaks the sheet cut left.
OPEN = {"listening": 6}  # bottom fraction that fades to transparent


def opening(alpha: np.ndarray, radius: int) -> np.ndarray:
    """Horizontal min then max filter: removes features narrower than 2*radius+1 px."""
    padded = np.pad(alpha, ((0, 0), (radius, radius)), mode="edge")
    shifts = [padded[:, i : i + alpha.shape[1]] for i in range(2 * radius + 1)]
    eroded = np.min(shifts, axis=0)
    padded = np.pad(eroded, ((0, 0), (radius, radius)), mode="edge")
    shifts = [padded[:, i : i + alpha.shape[1]] for i in range(2 * radius + 1)]
    return np.max(shifts, axis=0)


def largest_component(mask: np.ndarray) -> np.ndarray:
    """Keep the character, drop detached specks and lines (4-connected, iterative flood fill)."""
    labels = np.zeros(mask.shape, np.int32)
    best, best_size, current = 0, 0, 0
    for y0, x0 in zip(*np.nonzero(mask)):
        if labels[y0, x0]:
            continue
        current += 1
        stack, size = [(y0, x0)], 0
        labels[y0, x0] = current
        while stack:
            y, x = stack.pop()
            size += 1
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = current
                    stack.append((ny, nx))
        if size > best_size:
            best, best_size = current, size
    return labels == best


def clean(name: str) -> None:
    path = DIR / f"{name}.webp"
    image = np.array(Image.open(path).convert("RGBA"))
    alpha = image[:, :, 3].astype(np.float32)
    alpha = np.minimum(alpha, opening(alpha, OPEN.get(name, 3)))
    height = int(image.shape[0] * KEEP[name])
    image, alpha = image[:height], alpha[:height]
    alpha[~largest_component(alpha > 40)] = 0
    fade = max(1, int(height * FADE))
    alpha[height - fade :] *= np.linspace(1, 0, fade)[:, None]
    image[:, :, 3] = alpha.clip(0, 255).astype(np.uint8)
    # Trim empty columns and rows.
    ys, xs = np.nonzero(image[:, :, 3] > 8)
    image = image[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    Image.fromarray(image).save(path, "WEBP", quality=88, method=6)


if __name__ == "__main__":
    for pose in KEEP:
        clean(pose)
