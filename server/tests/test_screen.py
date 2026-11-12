"""Fox side of Screen protocol v1: intents, observations, fallback. No real services."""

import asyncio
import json

from open_tutor.agent import Tutor
from open_tutor.prompt import instructions
from open_tutor.screen_protocol import (
    ScreenTracker,
    build_intent_payload,
    build_observe_payload,
    parse_screen_meta,
    summarize_screen_context,
)


class FakeScreenParticipant:
    def __init__(self, intent_reply="auto", observe_reply="auto"):
        self.calls = []
        self.intent_reply = intent_reply
        self.observe_reply = observe_reply

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        data = json.loads(payload)
        self.calls.append((destination_identity, method, data))
        if method == "screen.intent":
            if isinstance(self.intent_reply, Exception):
                raise self.intent_reply
            if callable(self.intent_reply):
                return json.dumps(self.intent_reply(data))
            if isinstance(self.intent_reply, dict):
                return json.dumps(self.intent_reply)
            return json.dumps({"accepted": True, "intentId": data.get("intentId")})
        if method == "screen.observe":
            if isinstance(self.observe_reply, Exception):
                raise self.observe_reply
            if callable(self.observe_reply):
                return json.dumps(self.observe_reply(data))
            if isinstance(self.observe_reply, dict):
                return json.dumps(self.observe_reply)
            return json.dumps({"accepted": True, "observationId": data.get("observationId")})
        return json.dumps({"ok": True})

    async def set_attributes(self, attributes):
        pass

    async def send_text(self, *args, **kwargs):
        pass


class FakeScreenRoom:
    def __init__(self, participant):
        self.local_participant = participant


def make_tutor(participant, lesson="L1", intent_timeout=5.0, observe_timeout=1.0, grace=0.2):
    room = FakeScreenRoom(participant)
    tutor = Tutor({"name": "Leo", "grade": 3}, room, screen={"version": 1, "lessonId": lesson})
    tutor.child_identity = "learner-1"
    tutor.screen_intent_timeout = intent_timeout
    tutor.screen_observe_timeout = observe_timeout
    tutor.screen_context_grace = grace
    tutor.screen_tracker.intent_timeout = intent_timeout
    tutor.screen_tracker.observe_timeout = observe_timeout
    tutor.screen_tracker.context_grace = grace
    return tutor


async def wait_until(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting for condition"
        await asyncio.sleep(0.01)


def test_capability_parsing():
    assert parse_screen_meta({"screen": {"version": 1, "lessonId": "L1"}}) == {
        "capable": True, "version": 1, "lesson_id": "L1"}
    assert not parse_screen_meta({})["capable"]
    assert not parse_screen_meta({"screen": {"version": 2}})["capable"]
    assert not parse_screen_meta({"screen": "junk"})["capable"]
    legacy = Tutor({"name": "Leo"}, FakeScreenRoom(FakeScreenParticipant()))
    assert legacy.screen_capable is False
    capable = Tutor({"name": "Leo"}, FakeScreenRoom(FakeScreenParticipant()),
                    screen={"version": 1, "lessonId": "L9"})
    assert capable.screen_capable is True and capable.screen_lesson_id == "L9"


def test_prompt_mentions_screen_only_when_capable():
    legacy = instructions({"name": "Leo"})
    assert "show_screen" not in legacy
    capable = instructions({"name": "Leo"}, screen_capable=True)
    assert "show_screen" in capable and "reveal_screen" in capable and "observe_screen" in capable
    assert "commission_board" not in capable and "edit_board" not in capable
    assert "private" in capable.lower() and "explain in words instead" in capable.lower()


def test_intent_payload_shapes():
    show = build_intent_payload("i1", "L1", "show", need="n", background="b",
                                viewport={"w": 800, "h": 600, "device": "desktop"})
    assert show["op"] == "show" and show["need"] == "n" and show["viewport"]["w"] == 800
    reveal = build_intent_payload("i2", "L1", "reveal", target={"pageId": "p1", "revision": "r1"},
                                  viewport={"w": 1, "h": 1, "device": "d"})
    assert reveal["target"] == {"pageId": "p1", "revision": "r1"}
    obs = build_observe_payload("o1", "L1", "p1", "r1")
    assert obs == {"observationId": "o1", "lessonId": "L1", "pageId": "p1", "revision": "r1"}


async def test_show_returns_only_after_ready_plus_observation():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    task = asyncio.create_task(tutor.show_screen(None, need="clock need", background="Leo needs clock"))
    await wait_until(lambda: any(c[1] == "screen.intent" for c in participant.calls))
    # Immediate RPC ack must not finish the tool: it waits for async ready + pixels.
    await asyncio.sleep(0.05)
    assert not task.done()
    _, method, payload = participant.calls[0]
    assert method == "screen.intent" and payload["op"] == "show"
    assert payload["need"] == "clock need" and payload["viewport"]["w"] == 1920
    intent_id = payload["intentId"]
    assert await tutor.handle_screen_event(
        {"type": "ready", "intentId": intent_id, "lessonId": "L1",
         "page": {"id": "p1", "revision": "r1"}}) == "resolved"
    await wait_until(lambda: any(c[1] == "screen.observe" for c in participant.calls))
    obs_payload = [c[2] for c in participant.calls if c[1] == "screen.observe"][0]
    assert (obs_payload["pageId"], obs_payload["revision"]) == ("p1", "r1")
    obs_id = obs_payload["observationId"]
    assert tutor.handle_screen_pixels(obs_id, b"PNGDATA", {"observationId": obs_id})
    assert tutor.handle_screen_context(obs_id, {"observationId": obs_id, "lessonId": "L1",
                                                "page": {"id": "p1", "revision": "r1"},
                                                "summary": "clock shows 3",
                                                "privateTeaching": "solution x=3"})
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "p1" in result and "r1" in result and "screenshot" in result.lower()
    # Private teaching reaches the fox chat context, never the browser transcript.
    last = tutor.chat_ctx.items[-1]
    text = " ".join(c for c in last.content if isinstance(c, str))
    assert "x=3" in text and "clock" in text


async def test_prepare_returns_immediately_after_accept():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    result = await asyncio.wait_for(
        tutor.prepare_screen(None, need="map soon", background="geo next"), timeout=2.0)
    assert "Preparation accepted" in result and "Nothing is visible yet" in result
    assert participant.calls[0][1] == "screen.intent"
    assert participant.calls[0][2]["op"] == "prepare"
    # Fire-and-forget: no waiter left behind, but latest tracks the intent.
    assert not tutor.screen_tracker._intents
    assert tutor.screen_tracker.latest_intent_id is None


async def test_reveal_stale_does_not_observe():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    task = asyncio.create_task(tutor.reveal_screen(None, page_id="p9", revision="r9"))
    await wait_until(lambda: any(c[1] == "screen.intent" for c in participant.calls))
    intent_id = participant.calls[0][2]["intentId"]
    assert participant.calls[0][2]["target"] == {"pageId": "p9", "revision": "r9"}
    assert await tutor.handle_screen_event(
        {"type": "rejected", "intentId": intent_id, "lessonId": "L1",
         "reason": "stale: current is p2 r3"}) == "resolved"
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "stale" in result.lower() and "p2" in result and "r3" in result
    assert not [c for c in participant.calls if c[1] == "screen.observe"]


async def test_reveal_duplicate_still_observes_once():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    task = asyncio.create_task(tutor.reveal_screen(None, page_id="p1", revision="r1"))
    await wait_until(lambda: any(c[1] == "screen.intent" for c in participant.calls))
    intent_id = participant.calls[0][2]["intentId"]
    assert await tutor.handle_screen_event(
        {"type": "ready", "intentId": intent_id, "lessonId": "L1",
         "page": {"id": "p1", "revision": "r1"}, "reason": "duplicate: already visible"}) == "resolved"
    await wait_until(lambda: any(c[1] == "screen.observe" for c in participant.calls))
    obs_id = [c[2]["observationId"] for c in participant.calls if c[1] == "screen.observe"][0]
    tutor.handle_screen_pixels(obs_id, b"PNG", {})
    tutor.handle_screen_context(obs_id, {"observationId": obs_id, "lessonId": "L1",
                                         "page": {"id": "p1", "revision": "r1"},
                                         "summary": "already here"})
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "Already visible" in result and "p1" in result
    assert len([c for c in participant.calls if c[1] == "screen.observe"]) == 1


async def test_duplicate_ready_is_idempotent():
    tracker = ScreenTracker(lesson_id="L1")
    fut = tracker.track_intent("i1")
    assert tracker.resolve_event({"type": "ready", "intentId": "i1", "lessonId": "L1",
                                  "page": {"id": "p1", "revision": "r1"}}) == "resolved"
    assert tracker.current_page == {"id": "p1", "revision": "r1"}
    assert tracker.resolve_event({"type": "ready", "intentId": "i1", "lessonId": "L1",
                                  "page": {"id": "p1", "revision": "r1"}}) == "duplicate"
    assert (await fut)["type"] == "ready"


async def test_late_ready_updates_current_but_prepare_does_not():
    tracker = ScreenTracker(lesson_id="L1")
    tracker.track_intent("show-1")
    tracker.abandon_intent("show-1")  # e.g. tool timeout; late page still arrives
    assert tracker.resolve_event({"type": "ready", "intentId": "show-1", "lessonId": "L1",
                                  "page": {"id": "p1", "revision": "r1"}}) == "unknown"
    assert tracker.current_page == {"id": "p1", "revision": "r1"}
    tracker.note_intent_sent("prepare-1")
    assert tracker.resolve_event({"type": "ready", "intentId": "prepare-1", "lessonId": "L1",
                                  "page": {"id": "candidate", "revision": "r0"}}) == "unknown"
    assert tracker.current_page == {"id": "p1", "revision": "r1"}


def test_ids_are_namespaced_per_tutor_instance():
    first = ScreenTracker(lesson_id="L1")
    second = ScreenTracker(lesson_id="L1")
    assert first.new_intent_id() != second.new_intent_id()
    assert first.new_observation_id() != second.new_observation_id()


async def test_pixels_and_context_correlation():
    tracker = ScreenTracker(lesson_id="L1", observe_timeout=1.0, context_grace=0.2)
    tracker.track_observation("o1", "p1", "r1")
    # Context may arrive before pixels; both must correlate on the observation id.
    assert tracker.feed_context("o1", {"observationId": "o1", "lessonId": "L1",
                                       "page": {"id": "p1", "revision": "r1"}, "summary": "s"})
    assert tracker.feed_pixels("o1", b"PNG", {"observationId": "o1"})
    png, context = await tracker.wait_observation("o1")
    assert png == b"PNG" and context["summary"] == "s"
    # Unknown ids and lesson mismatches are ignored, not crashes.
    # Unknown ids and lesson mismatches are ignored, not crashes.
    assert tracker.feed_pixels("oX", b"x") is False
    tracker.track_observation("o2", "p1", "r1")
    assert tracker.feed_context("o2", {"observationId": "o2", "lessonId": "WRONG"}) is False
    assert tracker.feed_pixels("o2", b"wrong", {"pageId": "p2", "revision": "r1"}) is False
    assert tracker.feed_pixels("o2", b"wrong", {"pageId": "p1", "revision": "r2"}) is False
    assert tracker.feed_pixels("o2", b"right", {"pageId": "p1", "revision": "r1", "lessonId": "L1"}) is True
    tracker.track_observation("o3", "p1", "r1")
    assert tracker.feed_context("o3", {"observationId": "o3", "lessonId": "L1",
                                       "page": {"id": "p2", "revision": "r9"},
                                       "privateTeaching": "wrong solution"}) is False


async def test_missing_context_still_teaches_from_pixels():
    tracker = ScreenTracker(lesson_id="L1", observe_timeout=1.0, context_grace=0.05)
    tracker.track_observation("o1", "p1", "r1")
    assert tracker.feed_pixels("o1", b"PNG", {})
    png, context = await tracker.wait_observation("o1")
    assert png == b"PNG" and context is None


async def test_show_timeout_falls_back_to_words():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant, intent_timeout=0.15)
    result = await asyncio.wait_for(
        tutor.show_screen(None, need="n", background="b"), timeout=2.0)
    assert "may still finish" in result and "Continue in words" in result
    assert not [c for c in participant.calls if c[1] == "screen.observe"]


async def test_show_failed_falls_back_to_words():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    task = asyncio.create_task(tutor.show_screen(None, need="n", background="b"))
    await wait_until(lambda: any(c[1] == "screen.intent" for c in participant.calls))
    intent_id = participant.calls[0][2]["intentId"]
    assert await tutor.handle_screen_event(
        {"type": "failed", "intentId": intent_id, "lessonId": "L1",
         "reason": "model overloaded"}) == "resolved"
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "could not prepare" in result.lower() and "Explain in words instead" in result


async def test_show_rpc_rejection_falls_back():
    participant = FakeScreenParticipant(intent_reply={"accepted": False, "reason": "bad lesson"})
    tutor = make_tutor(participant)
    result = await tutor.show_screen(None, need="n", background="b")
    assert "did not accept" in result and "Explain in words instead" in result


async def test_observe_rpc_failure_falls_back():
    participant = FakeScreenParticipant(observe_reply={"accepted": False, "reason": "stale page"})
    tutor = make_tutor(participant)
    tutor.screen_tracker.current_page = {"id": "p1", "revision": "r1"}
    result = await asyncio.wait_for(tutor.observe_screen(None), timeout=2.0)
    assert "stale page" in result or "Explain in words instead" in result


async def test_capability_fallback_keeps_legacy_boards():
    room = FakeScreenRoom(FakeScreenParticipant())
    tutor = Tutor({"name": "Leo"}, room)
    tutor.child_identity = "learner-1"
    assert "commission_board" in await tutor.show_screen(None, need="n", background="b")
    assert "commission_board" in await tutor.reveal_screen(None, page_id="p1", revision="r1")
    assert "commission_board" in await tutor.observe_screen(None)


async def test_screen_mode_blocks_all_legacy_visible_writes():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    assert "disabled" in await tutor.commission_board(None, need="n", background="b")
    assert "disabled" in await tutor.edit_board(None, changes="c")
    assert "disabled" in await tutor.share_resource(None, title="t", url="https://example.com")
    assert participant.calls == []


async def test_answer_submitted_becomes_child_input():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    before = len(tutor.chat_ctx.items)
    assert await tutor.handle_screen_event(
        {"type": "answer-submitted", "lessonId": "L1",
         "page": {"id": "p1", "revision": "r1"}, "answer": "42"}) == "answer"
    assert len(tutor.chat_ctx.items) == before + 1
    text = " ".join(c for c in tutor.chat_ctx.items[-1].content if isinstance(c, str))
    assert "42" in text and "p1" in text


async def test_wrong_lesson_events_are_ignored():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant, lesson="L1")
    assert await tutor.handle_screen_event(
        {"type": "ready", "intentId": "i1", "lessonId": "OTHER",
         "page": {"id": "p1", "revision": "r1"}}) == "ignored"
    assert tutor.screen_tracker.current_page is None


async def test_rendered_page_change_quietly_updates_the_page_used_by_observe():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    original_chat = list(tutor.chat_ctx.items)
    for event in (
        {"type": "page-changed", "lessonId": "OTHER", "page": {"id": "wrong", "revision": "r1"}},
        {"type": "page-changed", "lessonId": "L1", "page": {"id": "missing-revision"}},
    ):
        assert await tutor.handle_screen_event(event) == "ignored"
    assert tutor.screen_tracker.current_page is None
    event = {"type": "page-changed", "lessonId": "L1", "page": {"id": "p1", "revision": "r1"}}
    assert await tutor.handle_screen_event(event) == "visible"
    assert await tutor.handle_screen_event(event) == "visible"
    assert list(tutor.chat_ctx.items) == original_chat
    task = asyncio.create_task(tutor.observe_screen(None))
    await wait_until(lambda: bool(participant.calls))
    payload = participant.calls[0][2]
    assert payload["pageId"] == "p1" and payload["revision"] == "r1"
    tutor.handle_screen_pixels(payload["observationId"], b"PNG", {})
    tutor.handle_screen_context(payload["observationId"], {
        "observationId": payload["observationId"], "lessonId": "L1",
        "page": event["page"], "visibleText": "Back on maths",
    })
    assert "Back on maths" in await task


async def test_superseded_show_notes_newer_intent():
    participant = FakeScreenParticipant()
    tutor = make_tutor(participant)
    task = asyncio.create_task(tutor.show_screen(None, need="n", background="b"))
    await wait_until(lambda: any(c[1] == "screen.intent" for c in participant.calls))
    intent_id = participant.calls[0][2]["intentId"]
    # A newer intent arrives while the first is still preparing.
    tutor.screen_tracker.note_intent_sent("i999", "show")
    assert await tutor.handle_screen_event(
        {"type": "ready", "intentId": intent_id, "lessonId": "L1",
         "page": {"id": "p1", "revision": "r1"}}) == "resolved"
    await wait_until(lambda: any(c[1] == "screen.observe" for c in participant.calls))
    obs_id = [c[2]["observationId"] for c in participant.calls if c[1] == "screen.observe"][0]
    tutor.handle_screen_pixels(obs_id, b"PNG", {})
    tutor.handle_screen_context(obs_id, {"observationId": obs_id, "lessonId": "L1",
                                         "page": {"id": "p1", "revision": "r1"}})
    result = await asyncio.wait_for(task, timeout=2.0)
    assert "superseded" in result.lower()


def test_context_summary_keeps_private_model_only():
    visible, private = summarize_screen_context({
        "visibleText": "a clock", "privateTeaching": "hidden solution 3",
        "sources": ["wikimedia"], "page": {"id": "p1", "revision": "r1"}})
    assert "clock" in visible and private == "hidden solution 3"
    assert summarize_screen_context(None) == ("", "")
