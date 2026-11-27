"""Only the screenshot the child can see stays in the tutor's context.

Every screen page and every applied change used to leave a high-detail PNG in
the live tutor's chat context forever, so a long session re-sent every earlier
screenshot with every voice turn. These tests pin the rule that replaced that:
keep the newest screen screenshot plus the newest shot of every live page (the
one on screen and any still held back), keep all the text, and never touch the
child's own homework images.
"""

import base64
import json

import pytest
from livekit.agents import llm
from unittest.mock import AsyncMock, Mock

from open_tutor.agent import SmartTutor
from open_tutor.screen import Screen
from open_tutor.screen_context import (
    SCREEN_EXTRA_KEY,
    STALE_SHOT_NOTE,
    count_screen_shots,
    prune_screen_shots,
    screen_tag,
    shots_kept,
)


def shot(label: str = "A") -> llm.ImageContent:
    data = base64.b64encode(label.encode()).decode()
    return llm.ImageContent(image=f"data:image/png;base64,{data}", inference_detail="high")


def ctx_with(*messages) -> llm.ChatContext:
    """Build a context from (text, image|None, tag|None) triples."""
    ctx = llm.ChatContext.empty()
    for text, image, tag in messages:
        content = [text] + ([image] if image is not None else [])
        ctx.add_message(role="user", content=content, **({"extra": tag} if tag else {}))
    return ctx


def images_of(ctx: llm.ChatContext) -> list[str]:
    return [part.image for item in ctx.items for part in item.content
            if isinstance(part, llm.ImageContent)]


def texts_of(ctx: llm.ChatContext) -> list[str]:
    return [part for item in ctx.items for part in item.content if isinstance(part, str)]


# ---- the pure rule ---------------------------------------------------------


def test_the_newest_screen_screenshot_is_the_only_one_kept():
    first, second = shot("one"), shot("two")
    ctx = ctx_with(
        ("[Screen page p1 ...] Source:\n<h1>Ett</h1>", first, screen_tag("page", "p1")),
        ("[Screen page p2 ...] Source:\n<h1>Tva</h1>", second, screen_tag("page", "p2")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p2"}) == 1
    assert images_of(ctx) == [second.image]
    # The page source survives: it carries the part ids reveal/point need.
    assert "<h1>Ett</h1>" in texts_of(ctx)[0]
    assert STALE_SHOT_NOTE in texts_of(ctx)


def test_a_message_without_an_image_is_left_exactly_as_it_was():
    ctx = ctx_with(
        ("[Screen page p1 ...]", None, screen_tag("page", "p1")),
        ("[Screen page p2 ...]", shot("two"), screen_tag("page", "p2")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p2"}) == 0
    assert texts_of(ctx) == ["[Screen page p1 ...]", "[Screen page p2 ...]"]


def test_homework_and_child_messages_are_never_touched():
    homework, page = shot("homework"), shot("page")
    ctx = ctx_with(
        ("[Shared homework: matte.jpg]", homework, None),
        ("Vad är klockan?", None, None),
        ("[Screen page p1 ...]", page, screen_tag("page", "p1")),
    )
    assert prune_screen_shots(ctx, keep=0, live_pages={"p1"}) == 1
    # keep=0 drops every screen screenshot (even live ones) and still leaves the child's photo.
    assert images_of(ctx) == [homework.image]


def test_a_held_page_keeps_its_shot_and_so_does_the_visible_page():
    """A page asked with show="hold" is the newest screenshot while the child
    is still looking at the page before it: both are worth re-sending."""
    visible, held = shot("visible"), shot("held")
    ctx = ctx_with(
        ("[Screen page p1 ...] is now ON SCREEN", visible, screen_tag("page", "p1")),
        ("[Screen page p2 ...] ready but NOT visible", held, screen_tag("page", "p2")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p1"}) == 0
    assert images_of(ctx) == [visible.image, held.image]


def test_the_visible_pages_newest_shot_wins_over_its_older_ones():
    page, patch, held = shot("page"), shot("patch"), shot("held")
    ctx = ctx_with(
        ("[Screen page p1 ...]", page, screen_tag("page", "p1")),
        ("[Screen change applied (page p1)]", patch, screen_tag("patch", "p1")),
        ("[Screen page p2 ...] ready but NOT visible", held, screen_tag("page", "p2")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p1"}) == 1
    assert images_of(ctx) == [patch.image, held.image]


def test_a_held_page_keeps_its_shot_even_when_it_is_not_the_newest():
    """p2 is still waiting for show_page while p3 is on screen: the tutor will
    be asked to teach from p2 later, so its screenshot is not stale."""
    first, held, newest = shot("first"), shot("held"), shot("newest")
    ctx = ctx_with(
        ("[Screen page p1 ...]", first, screen_tag("page", "p1")),
        ("[Screen page p2 ...] ready but NOT visible", held, screen_tag("page", "p2")),
        ("[Screen page p3 ...] is now ON SCREEN", newest, screen_tag("page", "p3")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p2", "p3"}) == 1
    assert images_of(ctx) == [held.image, newest.image]


def test_keeping_many_shots_is_the_old_behaviour():
    shots = [shot(str(n)) for n in range(4)]
    ctx = ctx_with(*[(f"[Screen page p{n} ...]", s, screen_tag("page", f"p{n}"))
                     for n, s in enumerate(shots)])
    assert prune_screen_shots(ctx, keep=99, live_pages={"p3"}) == 0
    assert images_of(ctx) == [s.image for s in shots]
    assert STALE_SHOT_NOTE not in texts_of(ctx)


def test_pruning_twice_changes_nothing_and_adds_no_second_note():
    ctx = ctx_with(
        ("[Screen page p1 ...]", shot("one"), screen_tag("page", "p1")),
        ("[Screen page p2 ...]", shot("two"), screen_tag("page", "p2")),
    )
    assert prune_screen_shots(ctx, keep=1, live_pages={"p2"}) == 1
    before = texts_of(ctx)
    assert prune_screen_shots(ctx, keep=1, live_pages={"p2"}) == 0
    assert texts_of(ctx) == before
    assert texts_of(ctx).count(STALE_SHOT_NOTE) == 1


def test_an_empty_context_and_a_text_only_context_are_no_ops():
    assert prune_screen_shots(llm.ChatContext.empty()) == 0
    ctx = ctx_with(("Hej!", None, None))
    assert prune_screen_shots(ctx) == 0
    assert count_screen_shots(ctx) == 0


def test_count_screen_shots_counts_only_tagged_images():
    ctx = ctx_with(
        ("[Shared homework]", shot("homework"), None),
        ("[Screen page p1 ...]", shot("page"), screen_tag("page", "p1")),
    )
    assert count_screen_shots(ctx) == 1


def test_the_screen_tag_never_reaches_the_provider():
    """The tag lives in ChatMessage.extra, which the provider formats filter
    down to their own keys. If that ever changed, worker bookkeeping would be
    sent to the model as part of the request."""
    ctx = ctx_with(("[Screen page p1 ...]", shot("one"), screen_tag("page", "p1")))
    for fmt in ("openai", "openai.responses"):
        messages, _ = ctx.to_provider_format(fmt)
        assert SCREEN_EXTRA_KEY not in json.dumps(messages)


# ---- the setting -----------------------------------------------------------


def test_shots_kept_defaults_to_one_and_reads_the_setting():
    assert shots_kept({}) == 1
    assert shots_kept({"TUTOR_SCREEN_SHOTS": "3"}) == 3
    assert shots_kept({"TUTOR_SCREEN_SHOTS": " 0 "}) == 0


def test_a_broken_shots_setting_fails_loudly():
    with pytest.raises(ValueError, match="whole number"):
        shots_kept({"TUTOR_SCREEN_SHOTS": "lots"})
    with pytest.raises(ValueError, match="negative"):
        shots_kept({"TUTOR_SCREEN_SHOTS": "-1"})


# ---- the live tutor --------------------------------------------------------


class FakeParticipant:
    def __init__(self):
        self.calls = []

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((method, json.loads(payload)))
        return '{"ok":true}'

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


class FakeSession:
    agent_state = "listening"
    user_state = "listening"

    def __init__(self):
        self.generate_reply = Mock()


def make_screen(tmp_path, bodies=None):
    """A screen whose renders are distinct, so each page gets its own PNG."""
    shots = {"n": 0}
    answers = list(bodies or ["<h1>Ett</h1>", "<h1>Tva</h1>", "<h1>Tre</h1>"])

    async def model(system, user, images, look_png):
        return answers[min(shots["n"], len(answers) - 1)]

    async def render(body, patch, history, w, h):
        shots["n"] += 1
        return f"PNG{shots['n']}".encode(), []

    return Screen({"name": "Test", "grade": 4}, tmp_path / "pages",
                  model_call=model, render_page=render)


def smart_tutor(room, screen):
    tutor = SmartTutor({"name": "Leo", "grade": 7}, room, screen=screen)
    tutor.child_identity = "learner-1"
    return tutor


async def deliver(screen, tutor, ask, *, reveal="show"):
    """Run one screen job and hand its result to the tutor, as the worker does."""
    ready = []
    screen.on_page = ready.append
    screen.on_patch = ready.append
    screen.ask(ask, reveal=reveal)
    await screen.wait_idle()
    assert ready, "the screen produced nothing"
    result = ready[-1]
    if hasattr(result, "patch"):
        await tutor.screen_patch_ready(FakeSession(), result)
    else:
        await tutor.screen_page_ready(FakeSession(), result)
    return result


async def test_a_second_page_drops_the_first_pages_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen, room = make_screen(tmp_path), FakeRoom()
    tutor = smart_tutor(room, screen)

    await deliver(screen, tutor, "En sida om klockan")
    assert count_screen_shots(tutor.chat_ctx) == 1
    await deliver(screen, tutor, "En sida om bråk")

    assert count_screen_shots(tutor.chat_ctx) == 1
    assert images_of(tutor.chat_ctx) == ["data:image/png;base64,"
                                         + base64.b64encode(b"PNG2").decode()]
    # Nothing textual was lost: both pages still describe themselves.
    joined = "\n".join(texts_of(tutor.chat_ctx))
    assert "<h1>Ett</h1>" in joined and "<h1>Tva</h1>" in joined
    assert STALE_SHOT_NOTE in joined
    assert tutor.screen_shots_dropped == 1
    assert tutor.context_stats_for_analytics() == {
        "screen_shots_dropped": 1, "screen_shots_kept_setting": 1}
    await screen.aclose()


async def test_a_change_to_the_visible_page_supersedes_its_page_screenshot(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen, room = make_screen(tmp_path), FakeRoom()
    tutor = smart_tutor(room, screen)

    await deliver(screen, tutor, "En sida om klockan")
    assert screen.visible_id == "p1"

    async def patch_model(system, user, images, look_png):
        return '<ot-patch target="klocka"><ot-clock time="7:30"></ot-clock></ot-patch>'

    screen._model_call = patch_model
    patch = await deliver(screen, tutor, "Visa halv sju istället")

    assert patch.page_id == "p1"
    # The page's own shot is stale the moment the change lands on it.
    assert count_screen_shots(tutor.chat_ctx) == 1
    assert images_of(tutor.chat_ctx) == ["data:image/png;base64,"
                                         + base64.b64encode(b"PNG2").decode()]
    joined = "\n".join(texts_of(tutor.chat_ctx))
    assert 'target="klocka"' in joined and "<h1>Ett</h1>" in joined
    await screen.aclose()


async def test_a_held_page_keeps_both_shots_then_settles_back_to_one(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen, room = make_screen(tmp_path), FakeRoom()
    tutor = smart_tutor(room, screen)

    await deliver(screen, tutor, "En sida om klockan")           # p1, shown
    await deliver(screen, tutor, "Ett facit", reveal="hold")      # p2, held
    # The child sees p1; p2 is waiting for show_page. Both are live.
    assert count_screen_shots(tutor.chat_ctx) == 2

    await deliver(screen, tutor, "En sida om bråk")               # p3, shown
    # p1 is gone from the screen and p2 is still held: two live shots again.
    assert screen.unshown_pages() == {"p2"}
    assert count_screen_shots(tutor.chat_ctx) == 2
    kept = images_of(tutor.chat_ctx)
    assert kept == ["data:image/png;base64," + base64.b64encode(b"PNG2").decode(),
                    "data:image/png;base64," + base64.b64encode(b"PNG3").decode()]

    # Once the held page has been shown, it is an ordinary past page: the next
    # page leaves one screenshot behind.
    assert "now visible" in await tutor.show_page(AsyncMock(), page_id="p2")
    assert screen.unshown_pages() == set()
    await deliver(screen, tutor, "En sida om geometri")            # p4, shown
    assert count_screen_shots(tutor.chat_ctx) == 1
    await screen.aclose()


async def test_homework_images_survive_every_page(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_LOOK", "0")
    screen, room = make_screen(tmp_path), FakeRoom()
    tutor = smart_tutor(room, screen)

    photo = shot("homework")
    await tutor.add_homework([photo], "matte.jpg, sida 1 av 1")
    await deliver(screen, tutor, "En sida om klockan")
    await deliver(screen, tutor, "En sida om bråk")

    assert photo.image in images_of(tutor.chat_ctx)
    assert count_screen_shots(tutor.chat_ctx) == 1
    await screen.aclose()


async def test_the_setting_can_keep_every_screenshot(tmp_path, monkeypatch):
    """TUTOR_SCREEN_SHOTS=99 is the behaviour before the prune existed, so a
    session can be compared against it without a code change."""
    monkeypatch.setenv("SCREEN_LOOK", "0")
    monkeypatch.setenv("TUTOR_SCREEN_SHOTS", "99")
    screen, room = make_screen(tmp_path), FakeRoom()
    tutor = smart_tutor(room, screen)

    await deliver(screen, tutor, "En sida om klockan")
    await deliver(screen, tutor, "En sida om bråk")
    assert count_screen_shots(tutor.chat_ctx) == 2
    assert tutor.screen_shots_dropped == 0
    await screen.aclose()


async def test_a_broken_setting_fails_when_the_tutor_is_built(tmp_path, monkeypatch):
    monkeypatch.setenv("TUTOR_SCREEN_SHOTS", "nope")
    screen = make_screen(tmp_path)
    with pytest.raises(ValueError, match="TUTOR_SCREEN_SHOTS"):
        smart_tutor(FakeRoom(), screen)
    await screen.aclose()
