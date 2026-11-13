"""Background voice cancellation on the child's audio input (TUTOR_NOISE_CANCELLATION).

Pinned here: the mode comes from the environment and nothing else, an unusable value fails
loudly instead of running unfiltered, `off` keeps today's session exactly as it was, and the
filter the session is given is the one the mode names (noise.py).
"""

import pytest
from livekit.agents.types import NOT_GIVEN

from open_tutor import noise


# ---- the setting ---------------------------------------------------------------------


def test_default_is_off():
    assert noise.noise_cancellation_mode({}) == "off"
    assert noise.noise_cancellation_mode({"TUTOR_NOISE_CANCELLATION": ""}) == "off"
    assert noise.noise_cancellation_mode({"TUTOR_NOISE_CANCELLATION": "   "}) == "off"


@pytest.mark.parametrize(
    "value, expected",
    [("off", "off"), ("nc", "nc"), ("bvc", "bvc"),
     ("BVC", "bvc"), (" Bvc \n", "bvc"), ("NC", "nc")],
)
def test_known_values(value, expected):
    assert noise.noise_cancellation_mode({"TUTOR_NOISE_CANCELLATION": value}) == expected


@pytest.mark.parametrize("value", ["true", "1", "on", "bvctelephony", "krisp", "ncc"])
def test_an_unknown_value_fails_instead_of_running_unfiltered(value):
    with pytest.raises(ValueError) as error:
        noise.noise_cancellation_mode({"TUTOR_NOISE_CANCELLATION": value})
    message = str(error.value)
    assert "TUTOR_NOISE_CANCELLATION" in message
    assert "off, nc, bvc" in message
    assert repr(value) in message


def test_the_module_level_default_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("TUTOR_NOISE_CANCELLATION", "bvc")
    assert noise.noise_cancellation_mode() == "bvc"
    monkeypatch.delenv("TUTOR_NOISE_CANCELLATION")
    assert noise.noise_cancellation_mode() == "off"


# ---- what the session is given -------------------------------------------------------


def test_off_leaves_the_audio_input_untouched():
    """Today's behaviour: no audio_input object at all, so RoomIO builds its own defaults."""
    assert noise.audio_input("off") is None
    options = noise.room_options("child-1", "off")
    assert options.audio_input is NOT_GIVEN
    assert options.participant_identity == "child-1"
    assert options.text_input is False  # the worker owns lk.chat (text_input.py)


@pytest.mark.parametrize(
    "mode, model_file",
    [("nc", "c8.f.s.026300-1.0.0_3.1.kef"), ("bvc", "hs.c6.f.m.75df8f.kef")],
)
def test_the_configured_filter_reaches_the_room_options(mode, model_file):
    options = noise.room_options("child-1", mode)
    audio_input = options.audio_input
    assert audio_input is not NOT_GIVEN
    # AudioInputOptions keeps the filter for the child's track; RoomIO hands it to
    # rtc.AudioStream, which runs it before the VAD and the recogniser.
    noise_cancellation = audio_input.noise_cancellation
    assert noise_cancellation.options["modelPath"].endswith(model_file)
    assert options.text_input is False


def test_an_unknown_mode_is_refused_by_the_builder_too():
    with pytest.raises(ValueError):
        noise.audio_input("bvc-telephony")


def test_off_does_not_import_the_native_filter():
    """The package loads a native filter and its models at import; `off` must not pay."""
    import subprocess
    import sys

    code = (
        "import sys, os;"
        "os.environ.pop('TUTOR_NOISE_CANCELLATION', None);"
        "from open_tutor import noise;"
        "noise.room_options('child-1', 'off');"
        "assert 'livekit.plugins.noise_cancellation' not in sys.modules"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=".")
    assert done.returncode == 0, done.stderr[-2000:]
