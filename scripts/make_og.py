"""OG share image for talarum.se (1200x630, no text or letters).

Composes the three companions' full figures from web/public/character/**
(hero.webp) on warm paper with a faint exercise-book grid, matching the
landing pages (2026-11-27). No text is drawn: the file must stay
free of letters for any locale.

Run: uv run --with pillow scripts/make_og.py   (or: python3 scripts/make_og.py)
Writes: web/public/og.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB_PUBLIC = ROOT / "web" / "public"

WIDTH, HEIGHT = 1200, 630
# Warm paper (2026-11-27), matching the landing pages (--tp-paper #f6f1e7,
# --tp-paper2 #fbf8f2), with a faint squared exercise-book grid and a soft
# warm tint behind each companion.
BG_TOP = (251, 248, 242)
BG_BOTTOM = (246, 241, 231)
HALO = (238, 228, 212)
GRID = (226, 225, 222)
GRID_STEP = 30
GLOWS = [(246, 214, 196), (240, 220, 222), (226, 228, 208)]

HEROES = [
    WEB_PUBLIC / "character" / "hero.webp",
    WEB_PUBLIC / "character" / "middle" / "hero.webp",
    WEB_PUBLIC / "character" / "upper" / "hero.webp",
]


def main() -> int:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        print("need Pillow: uv run --with pillow scripts/make_og.py", file=sys.stderr)
        return 1

    missing = [str(p) for p in HEROES if not p.is_file()]
    if missing:
        print(f"missing art: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Vertical gradient canvas.
    canvas = Image.new("RGB", (WIDTH, HEIGHT))
    top = Image.new("RGB", (1, 1), BG_TOP)
    bottom = Image.new("RGB", (1, 1), BG_BOTTOM)
    grad = Image.new("RGB", (1, HEIGHT))
    for y in range(HEIGHT):
        t = y / max(HEIGHT - 1, 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(
            top.getpixel((0, 0)), bottom.getpixel((0, 0)))))
    canvas.paste(grad.resize((WIDTH, HEIGHT)))

    # Faint squared grid, like the exercise book on the landing pages.
    draw = ImageDraw.Draw(canvas)
    for gx in range(0, WIDTH, GRID_STEP):
        draw.line([(gx, 0), (gx, HEIGHT)], fill=GRID, width=1)
    for gy in range(0, HEIGHT, GRID_STEP):
        draw.line([(0, gy), (WIDTH, gy)], fill=GRID, width=1)

    # Soft halo behind the group.
    halo = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(halo).ellipse([WIDTH // 2 - 420, 40, WIDTH // 2 + 420, HEIGHT + 160], fill=120)
    halo = halo.filter(ImageFilter.GaussianBlur(90))
    glow = Image.new("RGB", (WIDTH, HEIGHT), HALO)
    canvas = Image.composite(glow, canvas, halo)

    # Equal visual weight: same figure height, slight overlap, centred.
    figure_h = 500
    gap = -70
    figs = []
    for path in HEROES:
        im = Image.open(path).convert("RGBA")
        w = round(im.width * figure_h / im.height)
        # Premultiplied resize: plain RGBA LANCZOS rings into a faint haze
        # across the transparent box, which shows up on a light canvas.
        figs.append(im.convert("RGBa").resize((w, figure_h), Image.LANCZOS).convert("RGBA"))
    total = sum(f.width for f in figs) + gap * (len(figs) - 1)
    x = (WIDTH - total) // 2
    baseline = HEIGHT - 30
    # A soft glow behind each head, in that companion's band accent.
    gx = x
    for fig, colour in zip(figs, GLOWS):
        cx, cy = gx + fig.width // 2, baseline - fig.height + 170
        mask = Image.new("L", (WIDTH, HEIGHT), 0)
        ImageDraw.Draw(mask).ellipse([cx - 190, cy - 170, cx + 190, cy + 170], fill=150)
        mask = mask.filter(ImageFilter.GaussianBlur(70))
        canvas = Image.composite(Image.new("RGB", (WIDTH, HEIGHT), colour), canvas, mask)
        gx += fig.width + gap
    for fig in figs:
        canvas.paste(fig, (x, baseline - fig.height), fig)
        x += fig.width + gap

    out = WEB_PUBLIC / "og.png"
    canvas.save(out, "PNG")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
