"""Unit tests for the qualified length lint's decision logic (no browser, no key).

Imports only the pure functions from screen/tools/check_lengths.py: label
parsing, coordinate pairing and the median-scale verdict. Rendered shell
evidence lives in screen/review/2026-11-13-lengths/ and needs Chromium.
"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "lengths_probe", Path(__file__).parents[1] / "tools/check_lengths.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_parses_supported_units_with_comma_and_point():
    assert probe.parse_length_label("4 cm") == 40.0
    assert probe.parse_length_label("4,5 cm") == 45.0
    assert probe.parse_length_label("30 mm") == 30.0
    assert probe.parse_length_label("2 m") == 2000.0
    assert probe.parse_length_label("1 dm") == 100.0


def test_rejects_non_claims():
    for text in ["?", "x", "x + 2", "60°", "12 cm²", "5 cm2", "4", "$4$ cm",
                 "", "ett cm", "-3 cm", "0 cm", "3 kg", "4 cm²"]:
        assert probe.parse_length_label(text) is None, text


def test_consistent_rectangle_is_quiet():
    verdict = probe.analyse_polygon("0 0, 4 0, 4 3, 0 3", "4 cm | 3 cm | 4 cm | 3 cm")
    assert verdict["flags"] == [] and verdict["skipped"] is None


def test_scaled_copy_is_quiet():
    verdict = probe.analyse_polygon("0 0, 10 0, 10 7,5, 0 7,5", "4 cm | 3 cm | 4 cm | 3 cm")
    assert verdict["flags"] == []


def test_rounded_coordinates_pass():
    verdict = probe.analyse_polygon("0 0, 4 0, 2 3,46", "4 cm | 4 cm | 4 cm")
    assert verdict["flags"] == []


def test_mixed_compatible_units_pass():
    verdict = probe.analyse_polygon("0 0, 40 0, 40 30, 0 30", "4 cm | 30 mm | 0,04 m | 30 mm")
    assert verdict["flags"] == []


def test_four_vs_five_is_caught_with_direction():
    verdict = probe.analyse_polygon("0 0, 4 0, 4 3, 0 3", "5 cm | 3 cm | 4 cm | 3 cm")
    assert len(verdict["flags"]) == 1
    flag = verdict["flags"][0]
    assert flag["sides"] == [1] and flag["direction"] == "shorter"


def test_two_known_sides_disagree_jointly_without_direction():
    verdict = probe.analyse_polygon("0 0, 4 0, 0 3", "5 cm | 3 cm | ?")
    assert len(verdict["flags"]) == 1
    assert verdict["flags"][0]["sides"] == [1, 2]
    assert verdict["flags"][0]["direction"] == "disagree"


def test_two_known_sides_agreeing_stay_quiet():
    verdict = probe.analyse_polygon("0 0, 4 0, 0 3", "4 cm | ? | 3 cm")
    assert verdict["flags"] == []


def test_single_known_side_cannot_set_scale():
    verdict = probe.analyse_polygon("0 0, 4 0, 0 3", "4 cm | ? | ?")
    assert verdict["flags"] == [] and verdict["skipped"] is not None


def test_mixed_dimensions_skip_the_polygon():
    assert probe.analyse_polygon("0 0, 4 0, 0 3", "4 cm | 60° | 3 cm")["flags"] == []
    assert probe.analyse_polygon("0 0, 4 0, 0 3", "4 cm | 12 cm² | 3 cm")["flags"] == []


def test_degenerate_and_nonfinite_inputs_stay_quiet():
    assert probe.analyse_polygon("0 0, 0 0, 4 0, 4 3", "5 cm | 3 cm | 4 cm | 3 cm")["flags"] == []
    assert probe.analyse_polygon("0 0, x 1, 4 0", "5 cm | 3 cm | 4 cm")["flags"] == []
    assert probe.analyse_polygon("0 0, 4 0", "5 cm | 3 cm")["flags"] == []
