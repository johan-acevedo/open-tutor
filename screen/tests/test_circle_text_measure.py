"""A label beyond a segment endpoint must not be called a crossing."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "circle_text_probe", Path(__file__).parents[1] / "tools/probe_circle_text.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_wide_label_beyond_slanted_endpoint_is_clear():
    # The old normal-projection formula reported ~7 px overlap here.
    _, gap = probe.clearance({"x": 80, "y": 105, "w": 100, "h": 10},
                             {"x": 0, "y": 0}, {"x": 100, "y": 100})
    assert gap == 5


def test_slanted_segment_through_label_intersects():
    _, gap = probe.clearance({"x": 40, "y": 40, "w": 20, "h": 20},
                             {"x": 0, "y": 0}, {"x": 100, "y": 100})
    assert gap == 0


def test_parallel_segment_misses_label():
    _, gap = probe.clearance({"x": 40, "y": 40, "w": 20, "h": 20},
                             {"x": 0, "y": 30}, {"x": 100, "y": 30})
    assert gap == 10
