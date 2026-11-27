"""Keep the tutor's chat context down to the screenshot the child can see.

Every finished screen page and every applied change puts a message into the
live tutor's chat context: a line of text, the page (or patch) source, and a
high-detail PNG of what the browser now shows. Nothing ever removed the old
ones, so a 20-minute session with ten pages re-sent ten full-page screenshots
with every voice turn -- about 1 100 input tokens and 50-200 kB of base64 each,
uploaded again before the model could start its reply. Worse than the cost:
the model saw ten pictures of a screen that only ever shows one page, with no
reliable way to tell which one the child is actually looking at.

What this module keeps is the newest screenshot, plus the newest shot of every
*live* page: the one on screen, and any finished page the child has not seen
yet (asked for with ``show="hold"``). The page *source* stays: it
is small (a typical page body is under 1 kB), it carries the part ids that
``reveal`` and ``point`` need, and a held page's source is the only thing the
tutor has to teach from once ``show_page`` brings it in -- ``show_page``
answers with a one-line note, not a fresh screenshot.

Why mutating the retained context is safe here:

* Every tutor route sends the whole context on every request. The Responses
  route is built with ``store=False``, so the plugin never links two requests
  with ``previous_response_id`` and nothing depends on server-side state
  (``tutor_llm.build_route_llm``, livekit-plugins-openai 1.8.10).
* ``ChatContext.copy()`` is shallow: items are shared objects, and editing one
  in place is what ``tutor_llm.heal_tool_arguments`` already does per request.
* Pruning runs only when a new screen message is appended, so the oldest
  changed position is where the previous screen message sits -- a few turns
  back. The static prompt prefix, which is what the providers actually cache
  (Go reported ~3 300 of 3 340 tokens cached from the second call,
  docs/smart-screen.md), is never touched.
* Gemini's thought signatures ride on ``function_call`` items' ``extra``; this
  only edits the content of worker-written ``user`` messages.
* The tag below lives in ``ChatMessage.extra``, which the provider formats
  filter down to a fixed set of keys (``google``, ``livekit``, ``xai``), so it
  never reaches a provider and no text has to be parsed to find these
  messages again.

Homework images are deliberately left alone: they are the child's own work,
the reason the lesson exists, and the first photo (the exercise) is usually
the one that must survive. See docs/smart-screen.md for the open question.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from livekit.agents import llm

# ChatMessage.extra key marking a worker-written screen message. Provider
# formats keep only their own extra keys, so this stays inside the worker.
SCREEN_EXTRA_KEY = "open_tutor_screen"

# Left in place of a dropped screenshot, so the model is never told "the
# screenshot shows the page now" with no screenshot in the message.
STALE_SHOT_NOTE = (
    "[This screenshot is no longer in the context: only the newest screen "
    "screenshot is kept, because the screen shows one page at a time. The "
    "source above still describes this page.]"
)

DEFAULT_SHOTS_KEPT = 1


def shots_kept(environ: dict[str, str] | Any | None = None) -> int:
    """How many of the newest screen screenshots stay in the tutor's context.

    ``TUTOR_SCREEN_SHOTS`` (default 1). A large value keeps every screenshot,
    which is the behaviour before this module existed, so a session can be
    compared against it without a code change. Zero keeps none. A value that
    is not a whole number fails loudly at startup, like the screen's settings.
    """
    env = os.environ if environ is None else environ
    raw = str(env.get("TUTOR_SCREEN_SHOTS", DEFAULT_SHOTS_KEPT)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"TUTOR_SCREEN_SHOTS must be a whole number, not {raw!r}"
        ) from None
    if value < 0:
        raise ValueError(f"TUTOR_SCREEN_SHOTS must not be negative, not {raw!r}")
    return value


def screen_tag(kind: str, page_id: str) -> dict[str, dict[str, str]]:
    """The ``extra`` for a screen message: which kind, which page."""
    return {SCREEN_EXTRA_KEY: {"kind": kind, "page": page_id}}


def _tag(item: Any) -> dict[str, Any] | None:
    if getattr(item, "type", None) != "message":
        return None
    extra = getattr(item, "extra", None)
    if not isinstance(extra, dict):
        return None
    tag = extra.get(SCREEN_EXTRA_KEY)
    return tag if isinstance(tag, dict) else None


def _has_image(item: Any) -> bool:
    return any(isinstance(part, llm.ImageContent) for part in item.content)


def prune_screen_shots(chat_ctx: llm.ChatContext, *, keep: int = DEFAULT_SHOTS_KEPT,
                       live_pages: Iterable[str] | None = None) -> int:
    """Drop superseded screen screenshots in place; returns how many went.

    Keeps the ``keep`` newest screen screenshots, plus the newest screenshot of
    every page in ``live_pages``: the page the child can see, and any finished
    page the child has not seen yet (asked with ``show="hold"``). A held page
    is the one case where a screenshot that is not the newest still shows
    something real -- the tutor is expected to teach from it once ``show_page``
    brings it in, and ``show_page`` answers with a one-line note, not a fresh
    screenshot.

    Only screenshots are removed. Each message that loses one keeps all of its
    text and gains one short line saying the picture is gone, so the tutor is
    never left reading about a screenshot it cannot see.
    """
    shots = [item for item in chat_ctx.items if _tag(item) is not None and _has_image(item)]
    if not shots:
        return 0

    protected: set[str] = set()
    if keep > 0:
        protected.update(item.id for item in shots[-keep:])
        for page_id in set(live_pages or ()):
            for item in reversed(shots):
                if (_tag(item) or {}).get("page") == page_id:
                    protected.add(item.id)
                    break

    dropped = 0
    for item in shots:
        if item.id in protected:
            continue
        kept = [part for part in item.content if not isinstance(part, llm.ImageContent)]
        gone = len(item.content) - len(kept)
        if not gone:
            continue
        kept.append(STALE_SHOT_NOTE)
        # One attribute store, not an in-place list edit: a request being
        # serialized on another task sees either the old list or the new one.
        item.content = kept
        dropped += gone
    return dropped


def count_screen_shots(chat_ctx: llm.ChatContext) -> int:
    """How many screen screenshots the context still carries (for the log)."""
    return sum(
        1
        for item in chat_ctx.items
        if _tag(item) is not None
        for part in item.content
        if isinstance(part, llm.ImageContent)
    )
