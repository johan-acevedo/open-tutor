"""The board pane size the client reports, and the tools the tutor exposes.

The legacy board tools (``commission_board``/``edit_board``) were removed on
2026-11-18; the Smart Screen renders at the pane size measured here.
"""

import json

from open_tutor.agent import Tutor
from open_tutor.prompt import instructions


class FakeParticipant:
    def __init__(self, reply='{"ok":true}', error=None):
        self.calls, self.reply, self.error = [], reply, error

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        if self.error:
            raise self.error
        return self.reply

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self, **kwargs):
        self.local_participant = FakeParticipant(**kwargs)


def tutor(room, identity="learner-1", learner=None):
    t = Tutor(learner or {"name": "Leo", "grade": 7}, room)
    t.child_identity = identity
    return t


def test_prompt_forbids_narrating_tool_calls():
    text = instructions({"name": "Leo"})
    assert "Never describe tool calls" in text and "read out ids" in text


def test_board_size_defaults_when_the_client_reports_nothing():
    t = Tutor({"name": "Leo"}, FakeRoom())
    assert (t.board_w, t.board_h, t.board_device) == (1920, 1080, "desktop")


def test_board_size_updates_are_clamped_to_the_sane_range():
    from open_tutor.agent import clamp_board_size
    assert clamp_board_size(5000, 10) == (3840, 320)
    assert clamp_board_size("junk", None) == (1920, 1080)
    t = tutor(FakeRoom())
    t.update_board_size(5000, 10, "desktop")
    assert (t.board_w, t.board_h) == (3840, 320)
    t.update_board_size(800, 600, "tablet-with-a-very-long-name-here")
    assert (t.board_w, t.board_h) == (800, 600)
    assert len(t.board_device) <= 20
    before = t.board_device
    t.update_board_size(800, 600, None)  # no device in the payload keeps the old one
    assert t.board_device == before
