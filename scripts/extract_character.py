#!/usr/bin/env python3
"""Cut out the blue companion poses from the generated mockups.

Reads the agreed character sheet / screens under design/mockups/pass-2/,
removes the near-uniform dark background, feathers the edge and writes
transparent RGBA WebP files to web/public/character/.

Method (standard library + Pillow only). The hoodie's dark-navy shadow
areas are colour-identical to the background, so a single colour threshold
would eat into the body. Instead a tri-map is used:

* sure background: pixels close to the sampled background colour
  (``bg_threshold``) flood-filled from the top/left/right crop borders.
  The bottom edge is never seeded: it cuts through the hoodie torso.
* character: pixels far from the background (``fg_threshold``) plus a
  few hand-placed ``fg_strokes`` (marker segments deep inside torso
  shadow, as (x0, y0, x1, y1, radius) in final crop coordinates, i.e.
  after mirroring). The strokes only seed the proximity vote below; a
  stroke that missed the body stays a disconnected speck and is dropped
  with the other stray blobs, so they are safe to place approximately.
  They are needed because long, smooth hoodie shadow (sleeves, belly)
  can sit nearer to border background than to any fold highlight.
  Stray pills / bubbles / captions inside the crop are disconnected
  from the body, so they drop out with the blob filter.

Run from the repo root::

    python3 scripts/extract_character.py
"""

from __future__ import annotations

import sys
import warnings
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCKUPS = REPO_ROOT / "design" / "mockups" / "pass-2"
OUT_DIR = REPO_ROOT / "web" / "public" / "character"

MAX_HEIGHT = 900
WEBP_QUALITY = 88

# (left, upper, right, lower) in mockup pixels. Bottom edges cut through the
# hoodie torso; top/left/right edges keep a few px of background margin so
# the background fill can seed from there.
POSES = {
    # 00-character.png: four poses left to right, labels below y~810 excluded.
    "listening": {
        "src": "00-character.png",
        "box": (9, 100, 410, 790),
        "mirror": True,  # gaze is to viewer-right; tutor sits right of screen
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        # shadowed right sleeve + belly (final coords, i.e. mirrored).
        # The torso fills the whole lower crop; strokes stay well clear
        # of the silhouette and of the (non-existent here) finger gaps.
        "fg_strokes": [
            (30, 500, 30, 682, 3),
            (70, 350, 70, 682, 3),
            (140, 350, 140, 682, 3),
            (210, 350, 210, 682, 3),
            (280, 350, 280, 682, 3),
            (350, 350, 350, 682, 3),
        ],
    },
    "speaking": {
        "src": "00-character.png",
        "box": (411, 100, 841, 790),
        "mirror": False,
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        # shadowed left sleeve (kept below the glove) + panels/belly.
        # Strokes avoid the finger gaps (gloves end around y~570/620).
        "fg_strokes": [
            (45, 585, 45, 682, 3),
            (150, 450, 150, 682, 3),
            (220, 450, 220, 682, 3),
        ],
    },
    "thinking": {
        "src": "00-character.png",
        "box": (842, 100, 1268, 790),
        "mirror": False,
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        # shadowed elbow: solid crossed-arm mass here.
        "fg_strokes": [
            (40, 600, 40, 682, 3),
            (100, 450, 100, 682, 3),
            (200, 450, 200, 682, 3),
            (300, 450, 300, 682, 3),
        ],
    },
    "waiting": {
        "src": "00-character.png",
        "box": (1252, 100, 1663, 790),
        "mirror": False,
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        # shadowed left cuff/wrist + shirt (kept above the clasped
        # fingers so no finger slits are bridged).
        "fg_strokes": [
            (55, 560, 55, 682, 3),
            (100, 500, 100, 682, 3),
            (200, 500, 200, 580, 3),
        ],
    },
    # 02-greeting.png: frontal pose. Crop excludes the "Leo" pill (top right,
    # partially), the "Pratar" pill + caption (below y~688) and the dropzone.
    # Leftover pill slivers are disconnected -> dropped.
    "greeting": {
        "src": "02-greeting.png",
        "box": (1000, 25, 1572, 680),
        "mirror": False,
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        "fg_strokes": [],
    },
    # 04-maths-plain.png: pointing toward viewer-left. Crop excludes the
    # speech bubble (above, disconnected -> dropped) and the bottom bar.
    "pointing": {
        "src": "04-maths-plain.png",
        "box": (1155, 250, 1640, 806),
        "mirror": False,
        "bg_threshold": 10.0,
        "fg_threshold": 22.0,
        "fg_strokes": [],
    },
}


def get_pixels(img: Image.Image):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            return list(img.get_flattened_data())
        except AttributeError:
            return list(img.getdata())


def sample_background(crop: Image.Image) -> tuple[int, int, int]:
    """Median colour of a 12x12 patch at the crop's top-left (background)."""
    px = get_pixels(crop.crop((3, 3, 15, 15)))
    rs = sorted(p[0] for p in px)
    gs = sorted(p[1] for p in px)
    bs = sorted(p[2] for p in px)
    n = len(rs)
    return (rs[n // 2], gs[n // 2], bs[n // 2])


def flood_from_borders(w: int, h: int, ok: bytearray) -> bytearray:
    """4-connected fill restricted to ``ok`` pixels, seeded from the top,
    left and right borders. The bottom edge is never seeded."""
    filled = bytearray(w * h)
    stack = deque()
    for x in range(w):
        if ok[x]:
            stack.append(x)  # top row
    for y in range(h):
        if ok[y * w]:
            stack.append(y * w)  # left column
        if ok[y * w + w - 1]:
            stack.append(y * w + w - 1)  # right column
    while stack:
        i = stack.pop()
        if filled[i]:
            continue
        filled[i] = 1
        x = i % w
        y = i // w
        if x > 0 and ok[i - 1] and not filled[i - 1]:
            stack.append(i - 1)
        if x < w - 1 and ok[i + 1] and not filled[i + 1]:
            stack.append(i + 1)
        if y > 0 and ok[i - w] and not filled[i - w]:
            stack.append(i - w)
        if y < h - 1 and ok[i + w] and not filled[i + w]:
            stack.append(i + w)
    return filled


def chamfer_distance(w: int, h: int, markers: bytearray) -> list:
    """Squared-ish chamfer distance transform (weights 3/4 ~= euclidean).

    Returns a list of ints, 0 at marker pixels. Two raster passes."""
    INF = 1 << 30
    dp = [0 if markers[i] else INF for i in range(w * h)]
    # Forward: top-left -> bottom-right.
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if dp[i] == 0:
                continue
            best = dp[i]
            if x > 0 and dp[i - 1] + 3 < best:
                best = dp[i - 1] + 3
            if y > 0:
                if x > 0 and dp[i - w - 1] + 4 < best:
                    best = dp[i - w - 1] + 4
                if dp[i - w] + 3 < best:
                    best = dp[i - w] + 3
                if x < w - 1 and dp[i - w + 1] + 4 < best:
                    best = dp[i - w + 1] + 4
            dp[i] = best
    # Backward: bottom-right -> top-left.
    for y in range(h - 1, -1, -1):
        row = y * w
        for x in range(w - 1, -1, -1):
            i = row + x
            if dp[i] == 0:
                continue
            best = dp[i]
            if x < w - 1 and dp[i + 1] + 3 < best:
                best = dp[i + 1] + 3
            if y < h - 1:
                if x < w - 1 and dp[i + w + 1] + 4 < best:
                    best = dp[i + w + 1] + 4
                if dp[i + w] + 3 < best:
                    best = dp[i + w] + 3
                if x > 0 and dp[i + w - 1] + 4 < best:
                    best = dp[i + w - 1] + 4
            dp[i] = best
    return dp


def voronoi_fill(
    w: int, h: int, sure_bg: bytearray, sure_fg: bytearray
) -> bytearray:
    """Label every pixel by its nearest sure region (chamfer Voronoi).

    Colour alone cannot place the torso silhouette where hoodie shadow
    melts into the background, but euclidean proximity can: deep shadow
    far inside the body is much closer to a fold highlight or fur (sure
    foreground) than to any border background, while edge-blend fringe
    just outside the body is closest to the background. Sure pixels keep
    their label; only the uncertain band is decided. A 3x3 majority pass
    over the band removes speckles.
    """
    dist_bg = chamfer_distance(w, h, sure_bg)
    dist_fg = chamfer_distance(w, h, sure_fg)
    label = bytearray(w * h)
    band = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if sure_fg[i]:
                label[i] = 1
            elif not sure_bg[i]:
                band[i] = 1
                if dist_fg[i] <= dist_bg[i]:
                    label[i] = 1
                else:
                    # Deep interior (far from the left/right/top crop
                    # borders; the bottom edge cuts through the torso so
                    # it does not count) that is neither sure background
                    # nor sure foreground can only be hoodie shadow: the
                    # real background is flat and always sure-background
                    # hued, and stray UI lives near the borders. Claim it
                    # for the character.
                    edge = x
                    if w - 1 - x < edge:
                        edge = w - 1 - x
                    if y < edge:
                        edge = y
                    if edge > 60:
                        label[i] = 1
    # One 3x3 majority pass over band pixels.
    for y in range(1, h - 1):
        row = y * w
        for x in range(1, w - 1):
            i = row + x
            if not band[i]:
                continue
            votes = (
                label[i - w - 1] + label[i - w] + label[i - w + 1]
                + label[i - 1] + label[i] + label[i + 1]
                + label[i + w - 1] + label[i + w] + label[i + w + 1]
            )
            label[i] = 1 if votes >= 5 else 0
    return label


def fill_interior_holes(w: int, h: int, keep: bytearray) -> bytearray:
    """Make opaque everything not connected to the crop border.

    The hoodie casts colour-identical shadows, so the background fill can
    wick into the body through soft shadow junctions and punch transparent
    holes into the torso. Those holes are transparent regions fully
    enclosed by the character, while the real background (and any stray
    UI fully inside the crop, e.g. pill slivers) touches the crop border.
    """
    transparent = bytearray(w * h)
    for i in range(w * h):
        if not keep[i]:
            transparent[i] = 1
    # Seed from all four borders (bottom corners are background margins).
    filled = bytearray(w * h)
    stack = deque()
    for x in range(w):
        if transparent[x]:
            stack.append(x)
        if transparent[(h - 1) * w + x]:
            stack.append((h - 1) * w + x)
    for y in range(h):
        if transparent[y * w]:
            stack.append(y * w)
        if transparent[y * w + w - 1]:
            stack.append(y * w + w - 1)
    while stack:
        i = stack.pop()
        if filled[i]:
            continue
        filled[i] = 1
        x = i % w
        y = i // w
        if x > 0 and transparent[i - 1] and not filled[i - 1]:
            stack.append(i - 1)
        if x < w - 1 and transparent[i + 1] and not filled[i + 1]:
            stack.append(i + 1)
        if y > 0 and transparent[i - w] and not filled[i - w]:
            stack.append(i - w)
        if y < h - 1 and transparent[i + w] and not filled[i + w]:
            stack.append(i + w)
    out = bytearray(w * h)
    for i in range(w * h):
        if not filled[i]:
            out[i] = 1
    return out


def largest_component(w: int, h: int, fg: bytearray) -> bytearray:
    """Keep the largest 8-connected foreground blob (the character)."""
    seen = bytearray(w * h)
    best: bytearray | None = None
    best_size = 0
    total = 0
    for s in range(w * h):
        if not fg[s] or seen[s]:
            continue
        comp = bytearray(w * h)
        queue = deque([s])
        seen[s] = 1
        size = 0
        while queue:
            i = queue.popleft()
            comp[i] = 1
            size += 1
            x = i % w
            y = i // w
            for dx in (-1, 0, 1):
                nx = x + dx
                if nx < 0 or nx >= w:
                    continue
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ny = y + dy
                    if ny < 0 or ny >= h:
                        continue
                    j = ny * w + nx
                    if fg[j] and not seen[j]:
                        seen[j] = 1
                        queue.append(j)
        total += size
        if size > best_size:
            best_size = size
            best = comp
    if best is None:
        return bytearray(w * h)
    # Safety: if nothing dominates, keep everything rather than nuking.
    if best_size < total * 0.20:
        return bytearray(1 if fg[i] else 0 for i in range(w * h))
    return best


def extract(name: str, cfg: dict) -> Path:
    src = Image.open(MOCKUPS / cfg["src"]).convert("RGB")
    crop = src.crop(cfg["box"])
    if cfg["mirror"]:
        crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
    w, h = crop.size
    px = get_pixels(crop)

    bg = sample_background(crop)
    br, bgg, bb = bg
    bg2 = cfg["bg_threshold"] ** 2
    fg2 = cfg["fg_threshold"] ** 2
    sure_bg = bytearray(w * h)
    sure_fg = bytearray(w * h)
    for i, (r, g, b) in enumerate(px):
        dd = (r - br) ** 2 + (g - bgg) ** 2 + (b - bb) ** 2
        if dd < bg2:
            sure_bg[i] = 1
        elif dd > fg2:
            sure_fg[i] = 1

    # Hand-placed marker strokes deep inside torso shadow (final crop
    # coordinates, i.e. after mirroring). They seed the proximity vote;
    # a stroke that missed the body stays disconnected and is dropped.
    for x0, y0, x1, y1, rad in cfg.get("fg_strokes", []):
        steps = max(abs(x1 - x0), abs(y1 - y0)) + 1
        for s in range(steps):
            t = s / max(steps - 1, 1)
            cx = round(x0 + (x1 - x0) * t)
            cy = round(y0 + (y1 - y0) * t)
            for dy in range(-rad, rad + 1):
                ny = cy + dy
                if ny < 0 or ny >= h:
                    continue
                for dx in range(-rad, rad + 1):
                    if dx * dx + dy * dy > rad * rad:
                        continue
                    nx = cx + dx
                    if nx < 0 or nx >= w:
                        continue
                    j = ny * w + nx
                    sure_fg[j] = 1
                    sure_bg[j] = 0

    # The bottom edge cuts through the hoodie torso, so it is never used
    # to seed the background fill (its dark pixels are background-hued).
    # The Voronoi step below still assigns those rows by proximity.
    seed_bg = bytearray(sure_bg)
    for x in range(w):
        seed_bg[(h - 1) * w + x] = 0
    filled_bg = flood_from_borders(w, h, seed_bg)
    # Only background connected to the top/left/right borders counts -
    # interior background-hued pockets (hoodie shadow cores) stay
    # undecided for the Voronoi step.
    bg = bytearray(filled_bg)
    grown = voronoi_fill(w, h, bg, sure_fg)
    keep = largest_component(w, h, grown)
    keep = fill_interior_holes(w, h, keep)

    mask = Image.new("L", (w, h))
    mask.putdata([255 if keep[i] else 0 for i in range(w * h)])
    mask = mask.filter(ImageFilter.MinFilter(3))  # erode halo ~1px
    mask = mask.filter(ImageFilter.GaussianBlur(1.0))  # feather edge

    out = crop.copy()
    out.putalpha(mask)
    if out.size[1] > MAX_HEIGHT:
        out = out.resize(
            (round(out.size[0] * MAX_HEIGHT / out.size[1]), MAX_HEIGHT),
            Image.LANCZOS,
        )
    dest = OUT_DIR / f"{name}.webp"
    out.save(dest, "WEBP", quality=WEBP_QUALITY, method=6)
    return dest


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, cfg in POSES.items():
        dest = extract(name, cfg)
        im = Image.open(dest)
        kb = dest.stat().st_size / 1024
        mirrored = " mirrored" if cfg["mirror"] else ""
        print(f"{dest.name}: {im.size[0]}x{im.size[1]}{mirrored} {kb:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
