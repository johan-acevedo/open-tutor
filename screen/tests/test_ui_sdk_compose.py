"""Gating of the experiment UI SDK bundle in screenkit.compose.

The bundle is inlined only for the four experiment blocks (or on explicit
request); every other page composes exactly as before.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import pytest

import screenkit


BODY = pathlib.Path(__file__).resolve().parents[1] / "tools" / "fixtures" / "ui-sdk-blocks.html"
PLAIN = "<h1>Enheter</h1><ot-answer id=\"s\" label=\"Svar\"></ot-answer>"


def test_auto_detects_experiment_blocks():
    doc = screenkit.compose(BODY.read_text())
    assert '"ui-radio-group"' in doc


@pytest.mark.parametrize("tag", ["ot-order", "ot-match", "ot-sdk-choice", "ot-sdk-answer"])
def test_each_tag_triggers_the_bundle(tag):
    assert screenkit.has_sdk_blocks(f"<{tag} id=\"x\"></{tag}>")
    assert screenkit.has_sdk_blocks(f"<p><{tag} id=\"x\" label=\"y\">text</{tag}></p>")


def test_plain_pages_stay_bundle_free():
    assert not screenkit.has_sdk_blocks(PLAIN)
    doc = screenkit.compose(PLAIN)
    assert '"ui-radio-group"' not in doc
    assert "{{" not in doc


def test_explicit_flag():
    assert '"ui-radio-group"' in screenkit.compose(PLAIN, ui_sdk=True)
    assert '"ui-radio-group"' not in screenkit.compose(BODY.read_text(), ui_sdk=False)


def test_explicit_flag_without_bundle_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        screenkit.compose(PLAIN, shell=tmp_path, ui_sdk=True)
