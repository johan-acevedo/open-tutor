"""Companion poses keep one canvas per band, so the avatar never moves.

scripts/normalize_companion_poses.py pads every pose of a band onto that
band's common canvas (max width x max height, bottom-centre, unscaled).
This test reads the served WebP files and fails if any pose in a band
drifts off the common size again (e.g. after a re-export).
"""

from pathlib import Path

import pytest
from PIL import Image

CHARACTER = Path(__file__).resolve().parents[2] / "web" / "public" / "character"

BANDS = {
    "primary": CHARACTER,
    "middle": CHARACTER / "middle",
    "upper": CHARACTER / "upper",
}

POSES = ("greeting", "listening", "speaking", "thinking", "working", "waiting", "pointing")


@pytest.mark.parametrize("band", ["primary", "middle", "upper"])
def test_poses_share_one_canvas_per_band(band):
    sizes = {}
    for pose in POSES:
        path = BANDS[band] / f"{pose}.webp"
        assert path.is_file(), f"missing pose: {band}/{pose}"
        with Image.open(path) as image:
            assert image.mode == "RGBA", f"{band}/{pose} lost its alpha channel"
            sizes[pose] = image.size
    assert len(set(sizes.values())) == 1, f"{band} poses differ in canvas: {sizes}"
