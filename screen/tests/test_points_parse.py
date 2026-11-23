"""Every accepted `points` form, and the sliver verdict built on top of it.

Imports only the pure functions from screen/tools/check_points.py: coordinate
parsing, comma-only pair detection and the shape verdict. Rendered shell
evidence lives in screen/review/2026-11-22-points/ and needs Chromium.

The forms marked "worked before" are the ones the shell paired correctly
before 2026-11-22; the comma-only form is the one that drew a slanted line in
production and must pair the same way now.
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "points_probe", Path(__file__).parents[1] / "tools/check_points.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def parse(attr):
    return [(round(x, 6), round(y, 6)) for x, y in probe.parse_points(attr)]


# ---- forms that worked before the fix --------------------------------------

def test_documented_comma_space():
    # screen/REFERENCE.md: points="1 3, 2 3, 2 5"
    assert parse("1 3, 2 3, 2 5") == [(1, 3), (2, 3), (2, 5)]


def test_semicolons_between_pairs():
    assert parse("0 0; 4 0; 4 3") == [(0, 0), (4, 0), (4, 3)]


def test_whitespace_only():
    assert parse("0 0 4 0 4 3") == [(0, 0), (4, 0), (4, 3)]


def test_decimal_comma_inside_a_pair():
    # The brief's form: Swedish decimal commas, ", " between pairs.
    assert parse("1,5 2, 3 4,5") == [(1.5, 2), (3, 4.5)]
    # And a third pair, without a trailing comma after the last decimal.
    assert parse("1,5 2, 3 4,5 5 2") == [(1.5, 2), (3, 4.5), (5, 2)]


def test_comma_separated_decimal_list_keeps_its_old_reading():
    # "0,5,1,5" is ambiguous; the shell has always read it as integers, and the
    # fix only claims chunks that hold exactly one x y pair.
    assert parse("0,5,1,5") == [(0, 5)]


def test_parenthesised_pairs():
    assert parse("(0 0) (4 0) (4 3)") == [(0, 0), (4, 0), (4, 3)]


def test_true_minus():
    assert parse("0 0, \u22124 0, \u22124 3") == [(0, 0), (-4, 0), (-4, 3)]


def test_fractions_and_segment_from_to():
    assert parse("0 0, 1/2 3") == [(0, 0), (0.5, 3)]


def test_a_comma_only_list_with_a_bad_value_is_not_repaired():
    # One unusable chunk means the whole string keeps the old tokenisation, so a
    # coordinate that is not a number never turns into a guessed pair.
    assert probe.pair_commas("0 0, x 1") is None
    assert parse("0 0, x 1, 4 0") == [(0, 0), (1, 4)]  # old reading, shifted


# ---- the form that broke ---------------------------------------------------

def test_comma_only_pairs():
    # Production 2026-11-22: this rectangle drew as a thin slanted line, because
    # "0,4" was read as the decimal 0.4 and the pairing shifted.
    assert parse("0 0,4 0,4 3,0 3") == [(0, 0), (4, 0), (4, 3), (0, 3)]


def test_comma_only_needs_a_pair_in_every_chunk():
    # A decimal comma leaves a one-number chunk: fall back to the old split.
    assert probe.pair_commas("1,5 2, 3 4,5") is None
    assert probe.pair_commas("0 0 4 0") is None
    assert probe.pair_commas("0 0; 4 0") is None


def test_comma_only_keeps_decimal_commas_that_are_not_pairs():
    # Two decimal numbers separated by a space stay two numbers.
    assert parse("1,5 2,5") == [(1.5, 2.5)]


def test_trailing_and_doubled_commas_are_tolerated():
    assert parse("0 0, 4 0, 4 3,") == [(0, 0), (4, 0), (4, 3)]
    assert parse("0 0,,4 0") == [(0, 0), (4, 0)]


def test_comma_only_rectangle_has_the_documented_proportion():
    width, height = probe.drawn_extent(parse("0 0,4 0,4 3,0 3"))
    assert abs(width / height - 4 / 3) < 1e-9


# ---- the verdict the shape lint reports ------------------------------------

def test_a_normal_figure_is_quiet():
    assert probe.shape_verdict("0 0, 4 0, 4 3, 0 3")["kind"] is None
    assert probe.shape_verdict("0 0,4 0,4 3,0 3")["kind"] is None
    assert probe.shape_verdict("0 0, 4 0, 0 3")["kind"] is None


def test_thin_but_real_figures_stay_quiet():
    # A flat trapezoid and a long lean parallelogram are legitimate drawings.
    assert probe.shape_verdict("0 2, 4 2, 5.5 3, 1.5 3")["kind"] is None
    assert probe.shape_verdict("4 0, 5.5 1, 5.5 3, 4 2")["kind"] is None


def test_a_nearly_flat_triangle_is_a_sliver():
    assert probe.shape_verdict("0 0, 4 0, 4 0,3")["kind"] == "sliver"


def test_points_in_one_place_have_nothing_to_show():
    assert probe.shape_verdict("2 2, 2 2, 2 2")["kind"] == "identical"


def test_two_points_cannot_bound_a_plane_figure():
    # The old shell paired the production rectangle into two points and drew a
    # line; that shape is reported on its own, whatever the coordinates say.
    assert probe.shape_verdict("0 0, 4 0")["kind"] == "points"
    assert probe.shape_verdict("0 0, 4 0", polygon=False)["kind"] is None


def test_a_segment_and_a_missing_list_are_not_area_findings():
    assert probe.shape_verdict("0 0, 3 4", polygon=False)["skipped"] == \
        "a segment has no area"
    assert probe.shape_verdict("")["skipped"] == "needs points"


def test_free_and_schematic_figures_are_left_to_the_shell():
    # The opt-outs are read from the markup by the shell; the pure verdict only
    # describes the coordinates it is given.
    assert probe.shape_verdict("0 0, 4 0, 4 0,3")["kind"] == "sliver"
