"""The tutor worker: one LiveKit agent session per learner session.

Run with `python -m open_tutor.agent start` (or `dev` while developing).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    StopResponse,
    TurnHandlingOptions,
    cli,
    function_tool,
    llm,
    room_io,
)
from livekit.plugins import cartesia, elevenlabs, silero, soniox
from pydantic import ValidationError

from . import prompt
from .screen_protocol import (
    SCREEN_CONTEXT_GRACE,
    SCREEN_INTENT_TIMEOUT,
    SCREEN_OBSERVE_TIMEOUT,
    SCREEN_RPC_TIMEOUT,
    ScreenTracker,
    build_intent_payload,
    build_observe_payload,
    parse_screen_meta,
    summarize_screen_context,
    validate_screen_event,
)
from .board import (
    HtmlItem,
    Ids,
    Note,
    PendingItem,
    ResourceItem,
    youtube_embed,
)
from .config import AGENT_NAME, DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, env_float
from .debug_log import DebugLog, clear_active, record_active, set_active
from .dialogue_tts import DialogueTTS, is_dialogue_model
from .tutor_llm import build_llm, warm_up
from .speech import speakable_stream, unspoken_stream

log = logging.getLogger("open-tutor")

BOARD_RPC_TIMEOUT = 6.0
HOMEWORK_SETTLE = 1.2  # seconds to wait for more PDF pages before responding

# Screen protocol v1 (browser-owned workspace). RPCs ack immediately; the fox
# awaits async ready/observation events internally with longer budgets.

# Board size limits (CSS px). The client measures the real board pane and
# reports it; these are only the fallback when it reports nothing usable.
BOARD_MIN = 320
BOARD_MAX = 3840
DEFAULT_BOARD_W = 1920
DEFAULT_BOARD_H = 1080


def clamp_board_size(w: Any, h: Any) -> tuple[int, int]:
    """Clamp a client-reported board size to the sane pixel range."""
    try:
        cw = int(w)
    except (TypeError, ValueError):
        cw = DEFAULT_BOARD_W
    try:
        ch = int(h)
    except (TypeError, ValueError):
        ch = DEFAULT_BOARD_H
    return max(BOARD_MIN, min(cw, BOARD_MAX)), max(BOARD_MIN, min(ch, BOARD_MAX))


def build_stt() -> soniox.STT:
    return soniox.STT(
        params=soniox.STTOptions(
            model=os.environ.get("TUTOR_STT_MODEL", "stt-rt-v5"),
            language_hints=["sv"],
            # Children pause mid-thought; wait longer than the default before a turn ends.
            max_endpoint_delay_ms=int(env_float("TUTOR_STT_MAX_ENDPOINT_MS", 2500)),
        )
    )


def build_tts():
    provider = os.environ.get("TUTOR_TTS", "elevenlabs")
    if provider == "cartesia":
        return cartesia.TTS(
            model=os.environ.get("TUTOR_TTS_MODEL", "sonic-3"),
            voice=os.environ["TUTOR_TTS_VOICE"],
            language="sv",
        )
    model = os.environ.get("TUTOR_TTS_MODEL", DEFAULT_TTS_MODEL)
    voice = os.environ.get("TUTOR_TTS_VOICE") or DEFAULT_TTS_VOICE
    api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY") or ""
    if is_dialogue_model(model):
        # Eleven v4: the documented single-context text-to-dialogue socket (dialogue_tts.py).
        return DialogueTTS(api_key=api_key, voice_id=voice, model=model, language="sv")
    # Earlier models (e.g. eleven_flash_v2_5) through LiveKit's plugin, kept for rollback.
    return elevenlabs.TTS(model=model, voice_id=voice, language="sv", api_key=api_key)


def tts_route(engine) -> str:
    if isinstance(engine, DialogueTTS):
        return engine.route()
    return f"{engine.provider} {engine.model}"


class Tutor(Agent):
    def __init__(self, learner: dict[str, Any], room: rtc.Room, board: dict[str, Any] | None = None,
                 screen: dict[str, Any] | None = None, lesson_id: str = "") -> None:
        # `screen` is the bare screen dict from participant metadata
        # ({"version": 1, "lessonId": ...}); also accept the whole metadata
        # dict for convenience. Anything else means a legacy browser.
        if isinstance(screen, dict) and isinstance(screen.get("screen"), dict):
            screen_meta = parse_screen_meta(screen)
        else:
            screen_meta = parse_screen_meta({"screen": screen} if screen is not None else {})
        self.screen_capable = bool(screen_meta.get("capable"))
        self.screen_version = screen_meta.get("version")
        self.screen_lesson_id = (screen_meta.get("lesson_id") or lesson_id or "")[:80]
        super().__init__(instructions=prompt.instructions(learner, screen_capable=self.screen_capable))
        self.learner = learner
        board = board or {}
        self.board_w, self.board_h = clamp_board_size(board.get("w", DEFAULT_BOARD_W),
                                                     board.get("h", DEFAULT_BOARD_H))
        self.board_device = str(board.get("device", "desktop"))[:20]
        self.room = room
        self.ids = Ids()
        self.boards: dict[str, HtmlItem] = {}
        self._board_edit_locks: dict[str, asyncio.Lock] = {}
        self.current_board_id: str | None = None
        self.child_identity: str | None = None
        self.mode = "talking"
        self.notes_saved = 0
        self._http: aiohttp.ClientSession | None = None
        # Screen protocol v1 state. Timeouts are generous for browser model
        # work, short for the RPC ack itself; tests override per-instance.
        self.screen_intent_timeout = env_float("TUTOR_SCREEN_INTENT_TIMEOUT", SCREEN_INTENT_TIMEOUT)
        self.screen_observe_timeout = env_float("TUTOR_SCREEN_OBSERVE_TIMEOUT", SCREEN_OBSERVE_TIMEOUT)
        self.screen_context_grace = env_float("TUTOR_SCREEN_CONTEXT_GRACE", SCREEN_CONTEXT_GRACE)
        self.screen_tracker = ScreenTracker(
            lesson_id=self.screen_lesson_id or "lesson-unknown",
            intent_timeout=self.screen_intent_timeout,
            observe_timeout=self.screen_observe_timeout,
            context_grace=self.screen_context_grace,
        )

    # ---- board -----------------------------------------------------------------

    def update_board_size(self, w: Any, h: Any, device: Any = None) -> None:
        """Store the latest client-measured board pane size (mid-session resizes)."""
        self.board_w, self.board_h = clamp_board_size(w, h)
        if device is not None:
            self.board_device = str(device)[:20] or self.board_device
        record_active("board_size", {"w": self.board_w, "h": self.board_h,
                                       "device": self.board_device})

    async def _rpc(self, method: str, payload: dict[str, Any]) -> bool:
        if not self.child_identity:
            return False
        try:
            reply = await self.room.local_participant.perform_rpc(
                destination_identity=self.child_identity,
                method=method,
                payload=json.dumps(payload, ensure_ascii=False),
                response_timeout=BOARD_RPC_TIMEOUT,
            )
            try:
                data = json.loads(reply or "{}")
            except json.JSONDecodeError:
                data = {}
            ok = bool(data.get("ok"))
        except Exception as error:  # timeout, child left, or render error
            log.warning("board rpc %s failed: %s", method, error)
            record_active("board_ack", {"method": method, "id": payload.get("id"), "ok": False,
                                          "error": f"{type(error).__name__}: {error}"[:200]})
            return False
        log.info("board rpc %s %s acknowledged=%s", method, payload.get("id"), ok)
        record_active("board_ack", {"method": method, "id": payload.get("id"),
                                     "kind": payload.get("kind"), "title": payload.get("title"),
                                     "ok": ok})
        if ok:
            # Settled-size handshake: show/update acks carry the mounted pane
            # size after the arrival->teaching transition. Plain {ok:true}
            # peers keep working: no board key means no size update.
            board = data.get("board")
            if isinstance(board, dict) and board.get("w") is not None and board.get("h") is not None:
                try:
                    ack_w, ack_h = int(board.get("w")), int(board.get("h"))
                except (TypeError, ValueError, OverflowError):
                    pass
                else:
                    self.update_board_size(ack_w, ack_h, board.get("device"))
        return ok

    async def _show(self, item) -> str:
        shown = await self._rpc("board.show", item.model_dump(exclude_none=True))
        if not shown:
            return f"The board could not show item {item.id}. Explain in words instead, briefly."
        return f"Item {item.id} is now visible on the board. You can talk about it."

    async def _remove(self, item_id: str) -> None:
        """Take a placeholder off the board (best effort: a failed drawing must not linger)."""
        if not self.child_identity or not item_id:
            return
        try:
            await self.room.local_participant.perform_rpc(
                destination_identity=self.child_identity,
                method="board.remove",
                payload=json.dumps({"id": item_id}),
                response_timeout=BOARD_RPC_TIMEOUT,
            )
            record_active("board_ack", {"method": "board.remove", "id": item_id, "ok": True})
        except Exception as error:
            log.warning("board remove %s failed: %s", item_id, error)
            record_active("board_ack", {"method": "board.remove", "id": item_id, "ok": False,
                                          "error": f"{type(error).__name__}: {error}"[:200]})

    async def _show_final(self, item, pending_id: str) -> str:
        """Publish a finished drawing: in place of its placeholder when announced."""
        if not pending_id:
            return await self._show(item)
        shown = await self._rpc("board.update", item.model_dump(exclude_none=True))
        if shown:
            return f"Item {item.id} is now visible on the board. You can talk about it."
        await self._remove(pending_id)
        return (f"The drawing failed to appear (item {pending_id}). "
                "The placeholder was removed. Explain in words instead, briefly.")

    @function_tool()
    async def commission_board(self, context: RunContext, need: str, background: str,
                               title: str = "") -> str:
        """Ask the board model to make the board for this moment. One call does it all.

        You commission with background, never with content: describe what the child
        needs (who they are, what was just said, what should land), not what the
        board should look like. The board model decides the visualization, including
        whether anything interactive helps. This call first shows a placeholder so the
        child sees something is coming, then replaces it with the finished board.
        Say one short natural sentence while it draws (for example "Vänta lite, jag
        ritar det åt dig…") - once only. When this call returns, the board is on
        screen with a short note and a screenshot: look at both, then teach from what
        the board actually shows, in your own words as its author ("jag skriver
        upp...", never the board as a character).

        Args:
            need: What this moment needs, e.g. "Henning, grade 1, wants to see how a
                clock shows whole hours after asking to see the clock".
            background: 2-3 sentences a stranger would need: who the child is (level,
                language), what was just said, and what should land next.
            title: Short title of the board in the language you are speaking,
                e.g. "Klockan". Shown briefly on the placeholder.
        """
        from .board_model import render_board
        learner = (self.learner or {}).get("name", "") or ""
        pid = self.ids.next()
        # Placeholder reserves the initial height so the child sees something
        # at once. The ack carries the settled teaching-pane size
        # (arrival->teaching layout shift); freeze w/h/device AFTER it, before
        # rendering, so model, HtmlItem and screenshot all match even if later
        # board-size events arrive during the model await. The client scales
        # this design box to fit the current pane.
        try:
            ph = PendingItem(id=pid, title=(title or need)[:120], height=self.board_h)
            await self._rpc("board.show", ph.model_dump(exclude_none=True))
        except Exception:
            pass
        design_w, design_h, design_device = self.board_w, self.board_h, self.board_device
        try:
            result = await render_board(need, background, learner_name=learner,
                                        board_w=design_w, board_h=design_h,
                                        device=design_device)
        except Exception as error:
            await self._remove(pid)
            return (f"The board could not be made ({type(error).__name__}). "
                    "The placeholder was removed. Explain in words instead, briefly.")
        html = (result.get("html") or "")
        if "<html" not in html.lower():
            await self._remove(pid)
            return ("Invalid board: no HTML document. "
                    "The placeholder was removed. Explain in words instead.")
        try:
            item = HtmlItem(id=pid, title=(title or need)[:120],
                            html=html, height=design_h, width=design_w)
        except ValidationError as error:
            await self._remove(pid)
            return (f"Invalid board: {error.errors()[0]['msg']} "
                    "The placeholder was removed. Explain in words instead.")
        shown = await self._rpc("board.update", item.model_dump(exclude_none=True))
        if not shown:
            await self._remove(pid)
            return ("The drawing failed to appear "
                    f"(item {pid}). The placeholder was removed. Explain in words instead, briefly.")
        self.boards[pid] = item
        self.current_board_id = pid
        await self.add_board_seen(result.get("png"), result.get("note", ""),
                                  f"board {item.id}")
        return ("The board is on screen now and you can see its screenshot above. "
                "Start teaching from what it actually shows, as its author, right away. "
                "Do not repeat the waiting sentence - that moment has passed. "
                f"Its board id is {pid}: use edit_board with that id for requested changes, "
                f"commission_board only for a new topic. "
                f"[Board note: {result.get('note', '')[:500]}]")

    @function_tool()
    async def edit_board(self, context: RunContext, changes: str,
                         board_id: str = "") -> str:
        """Change the board already on screen. Same id, revised drawing.

        Use this for a requested change or correction to the existing
        visualization (fix, add, simplify, adjust what is shown). Use
        `commission_board` only when the topic itself changes. The call shows
        a brief placeholder at the same id, asks the board model to change
        only what was requested (previous HTML is sent, unrelated content and
        controls are preserved), then replaces the same id in place. Say one
        short waiting sentence once only, then teach from the screenshot when
        this call returns, as its author.

        Args:
            changes: What should change, e.g. "Make the clock show half past
                instead, keep everything else the same".
            board_id: Which saved board to edit, e.g. "b1". Omit to edit the
                most recent board.
        """
        target = (board_id or "").strip() or (self.current_board_id or "")
        if not target or target not in self.boards:
            if not self.boards:
                return ("There is no board on screen yet. Use commission_board "
                        "for a new topic instead of editing. No board was changed.")
            known = ", ".join(sorted(self.boards))
            recent = self.current_board_id or ""
            if not target:
                return (f"No board found (most recent is {recent}. Available: {known}). "
                        "No board was changed or rendered.")
            return (f"Unknown board id '{target}'. Available: {known}. Most recent is "
                    f"{recent}: omit board_id to edit it. No board was changed or rendered.")
        # Parallel tool calls editing one board must each start from the latest revision.
        async with self._board_edit_locks.setdefault(target, asyncio.Lock()):
            return await self._edit_saved_board(self.boards[target], changes)

    async def _failed_board_edit(self, saved: HtmlItem, reason: str) -> str:
        restored = await self._rpc("board.update", saved.model_dump(exclude_none=True))
        outcome = (f"The original board {saved.id} was restored." if restored else
                   f"I could not confirm restoring board {saved.id} on screen. "
                   "Its previous source is retained for a later retry.")
        return f"{reason} {outcome} Explain in words instead, briefly."

    async def _edit_saved_board(self, saved: HtmlItem, changes: str) -> str:
        from .board_model import render_board
        learner = (self.learner or {}).get("name", "") or ""
        target = saved.id
        # Edits keep the commissioned baseline size, not the current pane.
        edit_w = saved.width or self.board_w
        edit_h = saved.height or self.board_h
        try:
            ph = PendingItem(id=target, title=(saved.title or changes)[:120], height=edit_h)
            await self._rpc("board.update", ph.model_dump(exclude_none=True))
        except Exception:
            pass
        edit_device = self.board_device
        try:
            result = await render_board(changes, f"Revision of saved board {target}",
                                        learner_name=learner, board_w=edit_w, board_h=edit_h,
                                        device=edit_device, previous_html=saved.html)
        except Exception as error:
            return await self._failed_board_edit(
                saved, f"The board could not be changed ({type(error).__name__}).")
        html = (result.get("html") or "")
        if "<html" not in html.lower():
            return await self._failed_board_edit(saved, "Invalid revised board: no HTML document.")
        try:
            item = HtmlItem(id=target, title=saved.title,
                            html=html, height=edit_h, width=edit_w)
        except ValidationError as error:
            return await self._failed_board_edit(saved, f"Invalid revised board: {error.errors()[0]['msg']}.")
        shown = await self._rpc("board.update", item.model_dump(exclude_none=True))
        if not shown:
            return await self._failed_board_edit(saved, f"The revised drawing failed to appear (item {target}).")
        self.boards[target] = item
        self.current_board_id = target
        await self.add_board_seen(result.get("png"), result.get("note", ""),
                                  f"board {item.id} revised")
        return ("The revised board is on screen now and you can see its screenshot above. "
                "Start teaching from what it actually shows, as its author, right away. "
                f"Its board id is still {target}. "
                f"[Board note: {result.get('note', '')[:500]}]")

    # ---- screen (protocol v1, browser-owned workspace) ----------------------------

    def screen_viewport(self) -> dict[str, Any]:
        return {"w": self.board_w, "h": self.board_h, "device": self.board_device}

    def _screen_fallback(self) -> str:
        return ("This browser does not support the Screen (no screen v1 capability). "
                "Use commission_board for a new topic or edit_board to revise what is shown. "
                "No Screen was changed.")

    async def _screen_rpc(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """One Screen RPC with a short ack timeout. Returns the parsed reply or None."""
        if not self.child_identity:
            return None
        try:
            reply = await self.room.local_participant.perform_rpc(
                destination_identity=self.child_identity,
                method=method,
                payload=json.dumps(payload, ensure_ascii=False),
                response_timeout=SCREEN_RPC_TIMEOUT,
            )
            try:
                data = json.loads(reply or "{}")
            except json.JSONDecodeError:
                data = {}
        except Exception as error:  # timeout, child left, validation failure
            log.warning("screen rpc %s failed: %s", method, error)
            record_active("screen_rpc", {"method": method, "ok": False,
                                           "error": f"{type(error).__name__}: {error}"[:200]})
            return None
        record_active("screen_rpc", {"method": method,
                                       "intent": payload.get("intentId") or payload.get("observationId"),
                                       "accepted": bool(data.get("accepted"))})
        return data if isinstance(data, dict) else {}

    async def add_screen_seen(self, png: bytes | None, context: dict[str, Any] | None,
                              label: str) -> None:
        """Feed an observed Screen page back to the tutor: pixels + concise context."""
        visible, private = summarize_screen_context(context)
        parts: list[Any] = []
        if png:
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(png).decode()}",
                inference_detail="high"))
        text = (f"[Screen now visible ({label})."
                f"{(' Visible: ' + visible[:800]) if visible else ''}"
                f"{(' Private teaching (use to guide, never read aloud or show): ' + private[:800]) if private else ''} "
                "Look at the screenshot and teach from what it actually shows.]"
        )
        record_active("screen_seen", {"label": label, "visible": visible[:300],
                                       "has_private": bool(private), "image": bool(png)})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)

    async def add_screen_answer(self, answer: str, page: dict[str, Any] | None = None) -> None:
        """Notify the tutor of an explicit child answer from the Screen."""
        where = ""
        if isinstance(page, dict) and page.get("id"):
            where = f" (page {page.get('id')} rev {page.get('revision', '?')})"
        text = (f"[Child submitted an answer on the Screen{where}: "
                f"{(answer or '')[:2000]!r}. Respond briefly to what they wrote.]"
        )
        record_active("screen_answer", {"answer": (answer or "")[:300], "page": page or {}})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text])
        await self.update_chat_ctx(ctx)

    async def handle_screen_event(self, event: dict[str, Any]) -> str:
        """Route one screen-event object. Returns disposition for the caller."""
        if not self.screen_capable:
            return "ignored"
        ok, _ = validate_screen_event(event)
        if not ok:
            return "ignored"
        if str(event.get("lessonId") or "") != self.screen_tracker.lesson_id:
            return "ignored"
        kind = event.get("type")
        if kind == "answer-submitted":
            await self.add_screen_answer(str(event.get("answer") or ""),
                                         event.get("page") if isinstance(event.get("page"), dict) else None)
            return "answer"
        return self.screen_tracker.resolve_event(event)

    def handle_screen_pixels(self, observation_id: str, png: bytes,
                             attrs: dict[str, Any] | None = None) -> bool:
        if not self.screen_capable:
            return False
        if not png or len(png) > 8_000_000:
            log.warning("screen pixels %s dropped (size %s)", observation_id, len(png) if png else 0)
            return False
        return self.screen_tracker.feed_pixels(observation_id, png, attrs or {})

    def handle_screen_context(self, observation_id: str, context: dict[str, Any]) -> bool:
        if not self.screen_capable:
            return False
        if not isinstance(context, dict):
            return False
        return self.screen_tracker.feed_context(observation_id, context)

    def close_screen(self) -> None:
        try:
            self.screen_tracker.close()
        except Exception:
            pass

    async def _observe_screen_page(self, page: dict[str, Any], label: str) -> str:
        """Observe an already-committed page and feed it to the chat. Returns tool text."""
        page_id = str((page or {}).get("id") or "")[:80]
        revision = str((page or {}).get("revision") or "")[:80]
        if not page_id:
            return ("The Screen reported ready without a page id. "
                    "No observation was made. Explain in words instead, briefly.")
        observation_id = self.screen_tracker.new_observation_id()
        self.screen_tracker.track_observation(observation_id, page_id, revision)
        payload = build_observe_payload(observation_id, self.screen_tracker.lesson_id,
                                        page_id, revision)
        rpc = await self._screen_rpc("screen.observe", payload)
        if rpc is None:
            self.screen_tracker.abandon_observation(observation_id)
            return (f"Page {page_id} rev {revision} is ready but the observation request failed. "
                    "Explain in words instead, briefly.")
        if not rpc.get("accepted"):
            self.screen_tracker.abandon_observation(observation_id)
            reason = str(rpc.get("reason") or "not accepted")[:200]
            return (f"Page {page_id} rev {revision} is ready but observation was {reason}. "
                    "Explain in words instead, briefly.")
        try:
            png, context = await self.screen_tracker.wait_observation(observation_id)
        except TimeoutError:
            return (f"Page {page_id} rev {revision} is ready but no pixels arrived in time. "
                    "Explain in words instead, briefly.")
        except asyncio.CancelledError:
            return (f"Page {page_id} rev {revision} observation was cancelled (session ending). "
                    "Explain in words instead, briefly.")
        visible, private = summarize_screen_context(context)
        await self.add_screen_seen(png, context, f"{label} {page_id} rev {revision}")
        private_hint = (f" Private solution for you only (never read aloud): {private[:500]}"
                        if private else "")
        visible_hint = f" Visible context: {visible[:500]}" if visible else ""
        return (f"The Screen page {page_id} rev {revision} is visible and you can see its screenshot above."
                f"{visible_hint}{private_hint} "
                "Teach from the pixels now, as its author. "
                f"Its page id is {page_id} rev {revision}: use reveal_screen to reveal its answer, "
                "observe_screen to look again.")

    @function_tool()
    async def show_screen(self, context: RunContext, need: str, background: str) -> str:
        """Ask the browser Screen to show this moment's visual. One call does it all.

        You commission with intent and background, never with content: describe what the
        child needs (who they are, what was just said, what should land), not what the
        page should look like. The browser Screen agent decides the medium and preparation.
        Say one short natural sentence while it prepares (for example \"Vänta lite, jag
        lägger upp det åt dig…\") - once only. When this call returns, the page is on
        screen with a screenshot: look at it, then teach from what it actually shows,
        using the private teaching without revealing it.

        Args:
            need: What this moment needs, e.g. \"Henning, grade 1, wants to see how a
                clock shows whole hours after asking to see the clock\".
            background: 2-3 sentences a stranger would need: who the child is (level,
                language), what was just said, and what should land next.
        """
        if not self.screen_capable:
            return self._screen_fallback()
        if not (need or "").strip() or not (background or "").strip():
            return ("show_screen needs both need and background "
                    "(who the child is, what was said, what should land). No Screen was changed.")
        intent_id = self.screen_tracker.new_intent_id()
        self.screen_tracker.track_intent(intent_id)
        payload = build_intent_payload(intent_id, self.screen_tracker.lesson_id, "show",
                                        need=need, background=background,
                                        viewport=self.screen_viewport())
        rpc = await self._screen_rpc("screen.intent", payload)
        if rpc is None:
            self.screen_tracker.abandon_intent(intent_id)
            return ("The Screen request failed (no acknowledgement). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        if not rpc.get("accepted"):
            self.screen_tracker.abandon_intent(intent_id)
            reason = str(rpc.get("reason") or "not accepted")[:200]
            return (f"The Screen did not accept the show request ({reason}). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        try:
            event = await self.screen_tracker.wait_intent(intent_id)
        except TimeoutError:
            return ("The Screen is still preparing (no ready after waiting). "
                    "The Screen is unchanged. Explain in words instead, briefly, "
                    "and try show_screen again later if seeing would still help.")
        except asyncio.CancelledError:
            return ("The Screen request was cancelled (session ending). "
                    "Explain in words instead, briefly.")
        kind = event.get("type")
        if kind == "rejected":
            reason = str(event.get("reason") or "rejected")[:200]
            return (f"The Screen rejected the show request ({reason}). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        if kind == "failed":
            reason = str(event.get("reason") or "failed")[:200]
            return (f"The Screen could not prepare the page ({reason}). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        if kind != "ready":
            return ("The Screen returned an unexpected outcome. "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        page = event.get("page") if isinstance(event.get("page"), dict) else {}
        superseded = ""
        if intent_id != self.screen_tracker.latest_intent_id:
            superseded = (" (A newer Screen intent has since been sent; "
                          "this page may already be superseded.)")
        observed = await self._observe_screen_page(page, "screen")
        return observed + superseded

    @function_tool()
    async def prepare_screen(self, context: RunContext, need: str, background: str) -> str:
        """Ask the browser Screen to prepare material in the background (no visible change).

        Fire-and-forget: returns as soon as the Screen accepts. The Screen may promote
        the candidate when a later show_screen asks for it. Use it when you expect to
        need a visual shortly (for example a map for the next question).

        Args:
            need: What the coming moment needs.
            background: 2-3 sentences a stranger would need.
        """
        if not self.screen_capable:
            return self._screen_fallback()
        if not (need or "").strip() or not (background or "").strip():
            return ("prepare_screen needs both need and background. No Screen was changed.")
        intent_id = self.screen_tracker.new_intent_id()
        payload = build_intent_payload(intent_id, self.screen_tracker.lesson_id, "prepare",
                                        need=need, background=background,
                                        viewport=self.screen_viewport())
        rpc = await self._screen_rpc("screen.intent", payload)
        if rpc is None:
            return ("The Screen preparation request failed (no acknowledgement). "
                    "Nothing was prepared. Continue without it.")
        if not rpc.get("accepted"):
            reason = str(rpc.get("reason") or "not accepted")[:200]
            return (f"The Screen did not accept preparation ({reason}). Nothing was prepared.")
        self.screen_tracker.note_intent_sent(intent_id)
        return (f"Preparation accepted (intent {intent_id}). Nothing is visible yet; "
                "the Screen prepares in the background. Call show_screen when seeing would help.")

    @function_tool()
    async def reveal_screen(self, context: RunContext, page_id: str, revision: str) -> str:
        """Reveal a prepared Screen answer on an already-known page/revision.

        Deterministic page operation (no new model turn): binds the exact page id
        and revision the Screen mentioned. A stale id is rejected without changing
        anything; a duplicate returns the already-visible page without re-applying.
        On success the revealed page is observed, so teach from its pixels.

        Args:
            page_id: The Screen page id to reveal, e.g. \"p3\".
            revision: The revision the Screen announced, e.g. \"r2\".
        """
        if not self.screen_capable:
            return self._screen_fallback()
        page_id = (page_id or "").strip()[:80]
        revision = (revision or "").strip()[:80]
        if not page_id or not revision:
            return ("reveal_screen needs both page_id and revision exactly as the Screen announced them. "
                    "No Screen was changed.")
        intent_id = self.screen_tracker.new_intent_id()
        self.screen_tracker.track_intent(intent_id)
        payload = build_intent_payload(intent_id, self.screen_tracker.lesson_id, "reveal",
                                        target={"pageId": page_id, "revision": revision},
                                        viewport=self.screen_viewport())
        rpc = await self._screen_rpc("screen.intent", payload)
        if rpc is None:
            self.screen_tracker.abandon_intent(intent_id)
            return ("The Screen reveal failed (no acknowledgement). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        if not rpc.get("accepted"):
            self.screen_tracker.abandon_intent(intent_id)
            reason = str(rpc.get("reason") or "not accepted")[:200]
            return (f"The Screen did not accept the reveal ({reason}). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        try:
            event = await self.screen_tracker.wait_intent(intent_id)
        except TimeoutError:
            return ("The Screen reveal is still pending (no outcome after waiting). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        except asyncio.CancelledError:
            return ("The Screen reveal was cancelled (session ending). "
                    "Explain in words instead, briefly.")
        kind = event.get("type")
        if kind == "rejected":
            reason = str(event.get("reason") or "rejected")[:300]
            return (f"That page/revision is stale ({reason}): another page is current. "
                    "Do not retry the same id. Explain in words instead, briefly, "
                    "or call show_screen for the current need.")
        if kind == "failed":
            reason = str(event.get("reason") or "failed")[:200]
            return (f"The Screen could not reveal {page_id} rev {revision} ({reason}). "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        if kind != "ready":
            return ("The Screen reveal returned an unexpected outcome. "
                    "The Screen is unchanged. Explain in words instead, briefly.")
        page = event.get("page") if isinstance(event.get("page"), dict) else {}
        duplicate = ""
        if str(event.get("reason") or "").lower().startswith("duplicate"):
            duplicate = " (Already visible: no change was applied.)"
        observed = await self._observe_screen_page(page or {"id": page_id, "revision": revision},
                                                   "screen reveal")
        return observed + duplicate

    @function_tool()
    async def observe_screen(self, context: RunContext, page_id: str = "", revision: str = "") -> str:
        """Look again at the current Screen page (actual pixels + private context).

        Use it to re-check what is visible before teaching. Omit ids to observe the
        current page; pass an explicit id/revision only to re-observe a known page.

        Args:
            page_id: Screen page id, e.g. \"p3\". Omit for the current page.
            revision: Page revision, e.g. \"r2\". Omit for the current page.
        """
        if not self.screen_capable:
            return self._screen_fallback()
        page_id = (page_id or "").strip()[:80]
        revision = (revision or "").strip()[:80]
        if not page_id:
            current = self.screen_tracker.current_page or {}
            page_id = str(current.get("id") or "")
            revision = str(current.get("revision") or "")
        if not page_id:
            return ("There is no Screen page yet. Use show_screen for the current need. "
                    "No observation was made.")
        return await self._observe_screen_page({"id": page_id, "revision": revision}, "screen observe")

    # ---- resources ---------------------------------------------------------------

    @function_tool()
    async def find_resources(self, context: RunContext, query: str, videos: bool = True) -> str:
        """Search the public web for a short educational video or reading. Returns candidates.

        Args:
            query: What to look for, in Swedish or English, e.g. "dubbelbindning kemi förklaring".
            videos: Prefer videos (YouTube) when true.
        """
        key = os.environ.get("EXA_API_KEY")
        if not key:
            return "Search is not configured."
        body: dict[str, Any] = {
            "query": query,
            "numResults": 6,
            "type": "auto",
            "contents": {"text": {"maxCharacters": 300}},
        }
        if videos:
            body["includeDomains"] = ["youtube.com"]
        self._http = self._http or aiohttp.ClientSession()
        try:
            async with self._http.post(
                "https://api.exa.ai/search",
                json=body,
                headers={"x-api-key": key},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as response:
                data = await response.json()
        except Exception as error:
            log.warning("exa search failed: %s", error)
            return "Search failed. Continue without a resource."
        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "published": (r.get("publishedDate") or "")[:10],
                "snippet": (r.get("text") or "")[:300],
            }
            for r in data.get("results", [])
        ]
        return json.dumps(results, ensure_ascii=False) if results else "No results."

    @function_tool()
    async def share_resource(self, context: RunContext, title: str, url: str, think_about: str = "") -> str:
        """Put one resource on the board for the child to watch or read now.

        Args:
            title: Short Swedish title.
            url: The resource URL from find_resources.
            think_about: One short thing to think about while watching, in Swedish.
        """
        from urllib.parse import urlparse

        if urlparse(url).scheme != "https":
            return "Only https links can be shared."
        item = ResourceItem(
            id=self.ids.next(),
            title=title,
            url=url,
            embedUrl=youtube_embed(url),
            source=(urlparse(url).hostname or "").removeprefix("www."),
            prompt=think_about or None,
        )
        result = await self._show(item)
        await self.set_mode("resource")
        return (
            result
            + " Say one short sentence (what to look for), then stay quiet while they watch or read. "
            "When they come back or press 'Klar', talk about it."
        )

    # ---- quiet work and memory -------------------------------------------------

    async def set_mode(self, mode: str) -> None:
        if mode == self.mode:
            return
        old = self.mode
        self.mode = mode
        record_active("mode", {"old": old, "mode": mode})
        try:
            await self.room.local_participant.set_attributes({"tutor.mode": mode})
        except Exception as error:
            log.warning("could not set mode: %s", error)

    @function_tool()
    async def start_quiet_work(self, context: RunContext) -> str:
        """The child is now working on their own (calculating, writing, reading). Wait quietly."""
        await self.set_mode("quiet")
        return "Quiet work started. Say at most one short encouraging sentence, then wait."

    @function_tool()
    async def stay_quiet(self, context: RunContext) -> None:
        """Say nothing now: the child is thinking aloud, mumbling, counting, or talking to someone else."""
        raise StopResponse()

    @function_tool()
    async def save_note(
        self, context: RunContext, topic: str, clicked: str = "", tricky: str = "", next_step: str = ""
    ) -> str:
        """Save a short learning note in this browser for next time.

        Args:
            topic: What they worked on, e.g. "Ekvationer med x på ena sidan".
            clicked: Evidence of what became clearer; empty is normal when unclear.
                Distinguish guided work from independent use on a fresh example.
                Visible answers and motivational points or preserved streaks are not
                evidence of independent success.
            tricky: What still needs help or remains uncertain, not a fixed learner trait.
            next_step: What to try next time.
        """
        return await self.send_note(topic, clicked, tricky, next_step)

    async def send_note(self, topic: str, clicked: str = "", tricky: str = "", next_step: str = "") -> str:
        note = Note(
            at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            topic=topic[:120],
            clicked=clicked[:300] or None,
            tricky=tricky[:300] or None,
            next=next_step[:300] or None,
        )
        try:
            await self.room.local_participant.send_text(
                note.model_dump_json(exclude_none=True),
                topic="note",
                destination_identities=[self.child_identity] if self.child_identity else None,
            )
        except Exception as error:
            log.warning("note send failed: %s", error)
            record_active("note", {"ok": False, "topic": topic,
                                     "error": f"{type(error).__name__}"})
            return "Could not save the note."
        self.notes_saved += 1
        record_active("note", {"ok": True, "topic": topic, "clicked": clicked,
                                "tricky": tricky, "next": next_step})
        return "Saved."

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        if self.mode != "talking":
            # The child spoke during quiet work or a resource; the model decides whether to answer.
            await self.set_mode("talking")
            new_message.content.insert(
                0,
                "[The child was working quietly / watching. If this is thinking aloud or not meant for "
                "you, call stay_quiet.] ",
            )

    # Tool calls arrive as structured calls and run as tools. Only the reply's words may
    # reach the voice, the caption and (through the caption) the chat history.
    def tts_node(self, text, model_settings):
        return Agent.default.tts_node(self, speakable_stream(text), model_settings)

    def transcription_node(self, text, model_settings):
        return Agent.default.transcription_node(self, unspoken_stream(text), model_settings)

    # ---- homework ----------------------------------------------------------------

    async def add_board_seen(self, png: bytes | None, note: str, label: str) -> None:
        """Feed the finished board back to the tutor: screenshot + short note."""
        parts: list[Any] = []
        if png:
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(png).decode()}",
                inference_detail="high"))
        text = f"[Board now on screen ({label}). {note[:500]} Look at the screenshot and teach from what it actually shows.]"
        record_active("board_seen", {"label": label, "note": note[:300],
                                       "image": bool(png)})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)

    async def add_homework(self, parts: list[Any], description: str) -> None:
        record_active("homework_added", {"description": description[:300],
                                           "parts": len(parts),
                                           "image_parts": sum(1 for p in parts if hasattr(p, "image"))})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[f"[Shared homework: {description}]", *parts])
        await self.update_chat_ctx(ctx)


def prompt_event(session: AgentSession, text: str):
    """Ask for a reply to something that happened in the session (not speech).

    Sent as a bracketed user-role event: some OpenAI-compatible endpoints reject a
    request whose only new content is a system instruction or that ends on the
    model's own turn.
    """
    return session.generate_reply(user_input=f"[Session event, not the child's words: {text}]")


def safe_interrupt(session: AgentSession, where: str) -> None:
    """Interrupt, tolerating a session that already closed.

    On 2026-11-06 the session closed on repeated provider 400s and a later
    `session.interrupt()` raised `RuntimeError: AgentSession isn't running`, which
    crashed the job before the room was deleted and left the browser sitting in a
    dead room. Interrupting a closed session is a no-op for us: there is nothing
    left to stop.
    """
    record_active("interrupt", {"where": where})
    try:
        session.interrupt()
    except RuntimeError:
        log.warning("interrupt skipped, session already closed (%s)", where)


server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.5)
    warm_up()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    child = await ctx.wait_for_participant()
    try:
        meta = json.loads(child.metadata or "{}")
        learner = meta.get("learner", {})
        board = meta.get("board", {}) or {}
        screen = meta.get("screen", {}) or {}
    except json.JSONDecodeError:
        learner = {}
        board = {}
        screen = {}

    tutor = Tutor(learner, ctx.room, board=board, screen=screen,
                  lesson_id=ctx.room.name or "")
    if tutor.screen_capable and not tutor.screen_tracker.lesson_id:
        tutor.screen_tracker.lesson_id = ctx.room.name or "lesson-unknown"
        tutor.screen_lesson_id = tutor.screen_tracker.lesson_id
    elif tutor.screen_capable and not tutor.screen_lesson_id:
        tutor.screen_lesson_id = tutor.screen_tracker.lesson_id
    tutor.child_identity = child.identity

    debug = DebugLog.create(ctx.room.name, learner, getattr(getattr(ctx, "job", None), "id", "?"))
    set_active(debug)

    voice = build_tts()
    log.info("tutor TTS route %s", tts_route(voice))
    session = AgentSession(
        stt=build_stt(),
        llm=build_llm(ctx.room.name),
        tts=voice,
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"min_delay": env_float("TUTOR_MIN_ENDPOINT", 0.6), "max_delay": 4.0},
            interruption={"enabled": True, "mode": "vad", "min_duration": 0.4},
        ),
        max_tool_steps=6,
    )

    @session.on("function_tools_executed")
    def tools_executed(event) -> None:
        # Names only: arguments can hold the child's words.
        log.info("tools executed: %s", ", ".join(call.name for call in event.function_calls))
        debug.record_sdk(event)

    for sdk_event in (
        "user_input_transcribed",
        "user_transcription_timeout",
        "conversation_item_added",
        "user_state_changed",
        "agent_state_changed",
        "speech_created",
        "tool_execution_updated",
        "agent_false_interruption",
        "overlapping_speech",
        "session_usage_updated",
        "error",
    ):
        session.on(sdk_event, debug.record_sdk)

    # ---- homework intake ----------------------------------------------------------
    pending: list[tuple[list[Any], str]] = []
    settle: asyncio.Task | None = None

    async def respond_to_homework() -> None:
        await asyncio.sleep(HOMEWORK_SETTLE)
        batch = list(pending)
        pending.clear()
        for parts, description in batch:
            await tutor.add_homework(parts, description)
        await tutor.set_mode("talking")
        safe_interrupt(session, "homework")
        debug.record("prompt", {"kind": "homework_shared", "items": len(batch)})
        prompt_event(session, "The child just shared homework (see the latest shared items). Say "
                     "briefly what you see and ask where they want to start.")

    def schedule_reply() -> None:
        nonlocal settle
        if settle and not settle.done():
            settle.cancel()
        settle = asyncio.create_task(respond_to_homework())

    async def on_homework_image(reader: rtc.ByteStreamReader, identity: str) -> None:
        info = reader.info
        data = bytearray()
        async for chunk in reader:
            data.extend(chunk)
            if len(data) > 8_000_000:
                log.warning("homework image too large, dropped")
                return
        mime = info.mime_type or "image/jpeg"
        attrs = dict(info.attributes or {})
        description = attrs.get("source") or info.name or "bild"
        if attrs.get("page"):
            description += f", sida {attrs['page']} av {attrs.get('pages', '?')}"
        description += f" (board id {attrs.get('itemId', '?')}, {attrs.get('kind', 'photo')})"
        debug.record("homework_shared", {"kind": "image", "description": description[:300],
                                           "bytes": len(data), "mime": mime})
        image = llm.ImageContent(image=f"data:{mime};base64,{base64.b64encode(bytes(data)).decode()}", inference_detail="high")
        pending.append(([image], description))
        schedule_reply()

    async def on_homework_text(reader: rtc.TextStreamReader, identity: str) -> None:
        text = (await reader.read_all())[:12000]
        attrs = dict(reader.info.attributes or {})
        description = f"pasted text (board id {attrs.get('itemId', '?')})"
        debug.record("homework_shared", {"kind": "text", "description": description,
                                           "chars": len(text), "text": text})
        pending.append(([text], description))
        schedule_reply()

    ending = asyncio.Event()

    async def on_session_event(reader: rtc.TextStreamReader, identity: str) -> None:
        try:
            event = json.loads(await reader.read_all())
        except json.JSONDecodeError:
            return
        debug.record("browser_event", {"type": str(event.get("type", "?"))[:40]})
        if event.get("type") == "end":
            ending.set()
        elif event.get("type") == "board-size":
            # The browser measures the real board pane (ResizeObserver) and
            # reports resizes/rotation mid-session; commission_board picks
            # the latest size up at render time.
            tutor.update_board_size(event.get("w"), event.get("h"), event.get("device"))
        elif event.get("type") == "resource-closed":
            await tutor.set_mode("talking")
            debug.record("prompt", {"kind": "resource_closed"})
            prompt_event(session, "The child finished the resource. Ask briefly what they noticed or thought.")

    def spawn(coro_fn):
        def handler(reader, identity):
            asyncio.create_task(coro_fn(reader, identity))
        return handler

    async def on_screen_event(reader: rtc.TextStreamReader, identity: str) -> None:
        try:
            event = json.loads(await reader.read_all())
        except json.JSONDecodeError:
            return
        if not tutor.screen_capable:
            return
        debug.record("screen_event", {"type": str(event.get("type", "?"))[:40],
                                         "intent": str(event.get("intentId", ""))[:20]})
        try:
            action = await tutor.handle_screen_event(event)
        except Exception as error:
            log.warning("screen event handling failed: %s", error)
            return
        if action == "answer":
            await tutor.set_mode("talking")
            safe_interrupt(session, "screen-answer")
            debug.record("prompt", {"kind": "screen_answer"})
            prompt_event(session, "The child submitted an answer on the Screen "
                         "(see the latest submitted answer). Respond briefly to what they wrote.")

    async def on_screen_pixels(reader: rtc.ByteStreamReader, identity: str) -> None:
        if not tutor.screen_capable:
            return
        info = reader.info
        attrs = dict(info.attributes or {})
        observation_id = str(attrs.get("observationId") or attrs.get("observation_id") or "")
        if not observation_id:
            return
        data = bytearray()
        async for chunk in reader:
            data.extend(chunk)
            if len(data) > 8_000_000:
                log.warning("screen pixels too large, dropped")
                return
        debug.record("screen_pixels", {"observation": observation_id[:20],
                                           "bytes": len(data)})
        tutor.handle_screen_pixels(observation_id, bytes(data), attrs)

    async def on_screen_context(reader: rtc.TextStreamReader, identity: str) -> None:
        if not tutor.screen_capable:
            return
        try:
            payload = json.loads(await reader.read_all())
        except json.JSONDecodeError:
            return
        observation_id = str(payload.get("observationId") or payload.get("observation_id") or "")
        if not observation_id:
            return
        debug.record("screen_context", {"observation": observation_id[:20],
                                            "has_private": bool(payload.get("privateTeaching"))})
        tutor.handle_screen_context(observation_id, payload)

    ctx.room.register_byte_stream_handler("homework", spawn(on_homework_image))
    ctx.room.register_text_stream_handler("homework-text", spawn(on_homework_text))
    ctx.room.register_text_stream_handler("session-event", spawn(on_session_event))
    ctx.room.register_text_stream_handler("screen-event", spawn(on_screen_event))
    ctx.room.register_byte_stream_handler("screen-pixels", spawn(on_screen_pixels))
    ctx.room.register_text_stream_handler("screen-context", spawn(on_screen_context))

    outcome = "unknown"
    try:
        await session.start(
            agent=tutor,
            room=ctx.room,
            room_options=room_io.RoomOptions(participant_identity=child.identity),
            # TUTOR_CLOUD_RECORDING=1 uploads session audio and transcripts to LiveKit
            # Cloud observability. Off by default; the local debug log (TUTOR_DEBUG_LOG=1)
            # is the reviewable trail when Cloud is off or unreachable.
            record=os.environ.get("TUTOR_CLOUD_RECORDING") == "1",
        )
        debug.record("worker_session_started", {
            "cloud_recording": os.environ.get("TUTOR_CLOUD_RECORDING") == "1"})
        await ctx.room.local_participant.set_attributes({"tutor.mode": "talking"})
        debug.record("prompt", {"kind": "greeting"})
        prompt_event(session, prompt.greeting_instruction(learner))

        outcome = await _run_until_done(ctx, session, tutor, debug, ending)
    except Exception as error:
        outcome = f"error: {type(error).__name__}: {error}"[:300]
        log.exception("session failed")
        raise
    finally:
        report_path = debug.finalize(outcome)
        if report_path is not None:
            log.info("debug session report: %s", report_path)
        clear_active()


async def _run_until_done(
    ctx: JobContext, session: AgentSession, tutor: Tutor, debug: DebugLog,
    ending: asyncio.Event,
) -> str:

    left = asyncio.Event()
    ctx.room.on("participant_disconnected", lambda p: p.identity == tutor.child_identity and left.set())
    closed = asyncio.Event()

    @session.on("close")
    def session_closed(event) -> None:
        # The agent is gone (e.g. repeated provider errors closed it). Wake up instead of
        # waiting for an end or a leave that may never come; the room is deleted below so
        # the browser shows its disconnected notice with a restart button.
        debug.record_sdk(event)
        closed.set()

    await asyncio.wait(
        [asyncio.create_task(ending.wait()), asyncio.create_task(left.wait()),
         asyncio.create_task(closed.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    if closed.is_set() and not ending.is_set() and not left.is_set():
        log.error("agent session closed before the child left or ended the session")
        outcome = "sdk_closed_early"
    elif ending.is_set():
        outcome = "ended_by_child"
        await tutor.set_mode("ending")
        safe_interrupt(session, "ending")
        try:
            debug.record("prompt", {"kind": "goodbye"})
            handle = prompt_event(session, prompt.END_INSTRUCTION)
            try:
                await asyncio.wait_for(handle.wait_for_playout(), timeout=30)
            except Exception as error:
                log.warning("goodbye did not finish: %s", error)
                debug.record("goodbye", {"ok": False, "error": f"{type(error).__name__}"})
        except RuntimeError as error:
            log.warning("could not say goodbye, session already closed: %s", error)
            debug.record("goodbye", {"ok": False, "error": "session already closed"})
        if tutor.notes_saved == 0:
            await tutor.send_note("Läxhjälp")
    elif left.is_set():
        outcome = "child_left"
        debug.record("child_left", {})
    tutor.close_screen()
    if tutor._http:
        await tutor._http.close()
    await session.aclose()
    # Deleting the room disconnects the browser, which then shows its end card.
    try:
        await ctx.delete_room()
        debug.record("room_deleted", {})
    except Exception as error:
        log.warning("could not delete room: %s", error)
        debug.record("room_deleted", {"ok": False, "error": f"{type(error).__name__}"})
    ctx.shutdown("session ended")
    return outcome


if __name__ == "__main__":
    cli.run_app(server)
