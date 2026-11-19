"""Companion poses keep one canvas per band, so the avatar never moves.

scripts/normalize_companion_poses.py scales every pose of a band to the
same character height and pads it onto that band's common canvas
(bottom-centre).
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


@pytest.mark.parametrize("band", ["primary", "middle", "upper"])
def test_character_has_the_same_height_in_every_pose(band):
    # The fox's working pose once filled its file while the others did not:
    # padding alone made the companion shrink and grow between poses.
    heights = {}
    for pose in POSES:
        with Image.open(BANDS[band] / f"{pose}.webp") as image:
            box = image.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
            heights[pose] = box[3] - box[1]
    assert max(heights.values()) <= min(heights.values()) * 1.05, f"{band}: {heights}"
