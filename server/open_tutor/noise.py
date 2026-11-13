"""Background voice cancellation on the tutor's audio input.

`sound in the room is treated as the child speaking` is what hurt real sessions: a parent and
a 13-year-old at one phone. LiveKit's enhanced noise cancellation runs **server-side on
inbound audio**, before the VAD and the speech recogniser, so a turn is only started from
audio that has already been filtered (docs.livekit.io/transport/media/noise-cancellation).

`TUTOR_NOISE_CANCELLATION` picks the mode (2026-11-14):

- `off` (default): today's behaviour. Nothing is filtered and the plugin is not imported.
- `nc`: Krisp NC. Removes non-speech noise (traffic, fans, music) and keeps every voice.
- `bvc`: Krisp BVC. NC plus removing non-primary voices, which is our case: one child near
  the phone and other talk in the room.

The filter and its model ships inside `livekit-plugins-noise-cancellation` and runs in this
worker process; the package still requires LiveKit Cloud, which our rooms already use.
LiveKit's "voice isolation" models (ai-coustics Voice Focus, Krisp VIVA) are a separate
package and are billed per minute; `server/README.md` records what each one costs.
"""

from __future__ import annotations

import os

from livekit.agents import room_io

ENV_NAME = "TUTOR_NOISE_CANCELLATION"
OFF = "off"
# The value is both the env value and the plugin's model name, so the log line, the debug
# trail and the docs use one spelling.
MODES = (OFF, "nc", "bvc")
DEFAULT_MODE = OFF


def noise_cancellation_mode(environ: dict[str, str] | None = None) -> str:
    """The configured mode. An unknown value raises instead of guessing.

    A worker with a typo in this variable must fail at start rather than run unfiltered
    while the operator believes the room is being cleaned.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(ENV_NAME) or "").strip().lower()
    if not raw:
        return DEFAULT_MODE
    if raw not in MODES:
        raise ValueError(
            f"{ENV_NAME} must be one of {', '.join(MODES)}, not {raw!r} "
            f"(use {OFF!r} for the unfiltered behaviour)"
        )
    return raw


def _filter_options(mode: str):
    # Imported here on purpose: the package loads a native filter and its model at import
    # time (about 70 MB of .kef files), so `off` must not pay for it. `warm_up` below pays
    # that cost at process prewarm instead of inside a session.
    from livekit.plugins import noise_cancellation

    models = {"nc": noise_cancellation.NC, "bvc": noise_cancellation.BVC}
    return models[mode]()


def warm_up(mode: str) -> None:
    """Load the filter's native side before any session needs it.

    The first import costs about a second and blocks the event loop. On 2026-11-14 that
    second landed inside a session on the dev setup and pushed the greeting back from
    0.3-0.4 s to 1.3 s. Importing and building the options at prewarm moves it to worker
    start, where nothing is waiting. Errors are not swallowed: a mode whose model cannot
    load should fail at boot.
    """
    if mode != OFF:
        audio_input(mode)


def audio_input(mode: str) -> room_io.AudioInputOptions | None:
    """RoomIO audio input options for the mode, or None for `off`."""
    if mode == OFF:
        return None
    if mode not in MODES:
        raise ValueError(f"unknown noise cancellation mode {mode!r}")
    return room_io.AudioInputOptions(noise_cancellation=_filter_options(mode))


def room_options(participant_identity: str, mode: str) -> room_io.RoomOptions:
    """The tutor's RoomIO options, with the child's audio filtered as configured.

    `text_input=False`: the worker owns lk.chat from connect time (see text_input.py), so
    RoomIO must not take that topic over.
    """
    options = room_io.RoomOptions(participant_identity=participant_identity, text_input=False)
    filtered = audio_input(mode)
    if filtered is not None:
        options.audio_input = filtered
    return options
