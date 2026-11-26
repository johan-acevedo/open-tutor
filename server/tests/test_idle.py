"""Idle-silence timeout: the clock policy, the setting, and the wiring.

All material here is synthetic and fictional. The clock is injected, so no
test sleeps or touches the network.
"""

import ast
from pathlib import Path

from open_tutor.idle import IDLE_TIMEOUT_DEFAULT_S, IdleWatch, idle_timeout_s


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_default_is_twenty_minutes():
    assert IDLE_TIMEOUT_DEFAULT_S == 1200.0
    assert idle_timeout_s({}) == 1200.0


def test_setting_reads_tutor_idle_timeout_s():
    assert idle_timeout_s({"TUTOR_IDLE_TIMEOUT_S": "60"}) == 60.0
    assert idle_timeout_s({"TUTOR_IDLE_TIMEOUT_S": "0"}) == 0.0
    assert idle_timeout_s({"TUTOR_IDLE_TIMEOUT_S": "-5"}) == -5.0
    # Garbage never breaks the worker: fall back to the default.
    assert idle_timeout_s({"TUTOR_IDLE_TIMEOUT_S": "soon"}) == 1200.0


def test_fires_after_the_timeout_of_silence():
    clock = FakeClock()
    watch = IdleWatch(timeout_s=1200.0, clock=clock)
    clock.advance(1199.0)
    assert not watch.expired()
    clock.advance(1.0)
    assert watch.expired()


def test_activity_restarts_the_clock():
    clock = FakeClock()
    watch = IdleWatch(timeout_s=1200.0, clock=clock)
    clock.advance(1100.0)
    watch.note_activity()  # the learner spoke, typed, or shared something
    clock.advance(1100.0)
    assert not watch.expired()
    clock.advance(100.0)
    assert watch.expired()


def test_disabled_when_zero_or_negative():
    clock = FakeClock()
    for timeout in (0.0, -1.0):
        watch = IdleWatch(timeout_s=timeout, clock=clock)
        clock.advance(10_000_0.0)
        assert not watch.expired()
        assert not watch.enabled


def test_never_fires_while_the_tutor_is_speaking():
    clock = FakeClock()
    watch = IdleWatch(timeout_s=60.0, clock=clock)
    clock.advance(3600.0)
    assert not watch.expired(speaking=True)
    assert watch.expired(speaking=False)


def _entrypoint(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "entrypoint":
            return node
    raise AssertionError("entrypoint not found in agent.py")


def test_entrypoint_wires_learner_activity_to_the_idle_clock():
    """Speech, typed chat, homework and page answers must reset the clock;
    tutor speech alone must not (it never calls note_activity)."""
    source = (Path(__file__).parent.parent / "open_tutor" / "agent.py").read_text()
    assert "typed.attach_typed_listener(idle.note_activity)" in source
    assert 'session.on("user_input_transcribed", lambda _event: idle.note_activity())' in source
    assert source.count("idle.note_activity") >= 5  # typed, speech, 2x homework, page answers


def test_entrypoint_tells_the_page_about_an_idle_end():
    """The worker sends the end reason on a tutor-event stream before deleting
    the room, so the page can show the normal end card instead of its
    disconnected banner."""
    source = (Path(__file__).parent.parent / "open_tutor" / "agent.py").read_text()
    assert '"tutor-event"' in source
    assert '"idle_timeout"' in source
    assert "say_idle_goodbye" in source
    assert "idle_done" in source
