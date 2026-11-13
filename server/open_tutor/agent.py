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
    APIConnectOptions,
    JobContext,
    JobProcess,
    RunContext,
    SessionConnectOptions,
    StopResponse,
    TurnHandlingOptions,
    cli,
    function_tool,
    llm,
)
from livekit.plugins import cartesia, elevenlabs, silero, soniox
from pydantic import ValidationError

from . import noise, prompt
from .board import (
    HtmlItem,
    Ids,
    Note,
    PageItem,
    PendingItem,
    ResourceItem,
    youtube_embed,
)
from .config import AGENT_NAME, DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, env_float
from .debug_log import DebugLog, clear_active, record_active, set_active
from .dialogue_tts import DialogueTTS, is_dialogue_model
from .deepgram_tts import DeepgramFluxTTS, DEFAULT_MODEL as DEEPGRAM_DEFAULT_MODEL, parse_expressivity
from .session_llm import SessionLLM
from .text_input import TOPIC_CHAT, TypedChat
from .fillers import DEFAULT_DELAY_S as DEFAULT_FILLER_DELAY, build_fillers
from .tutor_llm import build_session_llm, warm_up
from .speech import speakable_stream, unspoken_stream

log = logging.getLogger("open-tutor")

BOARD_RPC_TIMEOUT = 6.0
HOMEWORK_SETTLE = 1.2  # seconds to wait for more PDF pages before responding
# Per LLM attempt. The default (10 s, three retries) is what made a slow provider keep a
# child waiting about 50 s for a greeting on 2026-11-14. One retry, then the failover in
# session_llm.py or the spoken apology at the end of this file.
LLM_RETRY_INTERVAL_S = 0.5
BOARD_IN_PROGRESS = (
    "A drawing is already in progress. No additional drawing was started. "
    "Continue teaching in words and respond to the child. "
    "Wait for the finished board before requesting another drawing."
)
BOARD_STARTED = (
    "The drawing has started in the background; the finished board is not visible yet. "
    "Continue helping the child in words now: give a short useful explanation or "
    "ask a relevant question while it draws. Do not just announce a wait or describe "
    "the unseen board. Respond normally if the child speaks. "
    "The finished board and screenshot will arrive automatically; do not request another drawing."
)

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
    if provider == "deepgram":
        # Deepgram Flux TTS (/v2/speak) over streaming linear16 PCM, Swedish voice
        # flux-ludvig-sv with expressivity=1 (see deepgram_tts.py). No silent
        # fallback: a missing key or bad expressivity raises here, before the session.
        return DeepgramFluxTTS(
            model=os.environ.get("TUTOR_TTS_MODEL", DEEPGRAM_DEFAULT_MODEL),
            expressivity=parse_expressivity(
                os.environ.get("TUTOR_TTS_EXPRESSIVITY", "1")
            ),
            api_key=os.environ.get("DEEPGRAM_API_KEY") or None,
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
    @staticmethod
    def _instructions(learner: dict[str, Any]) -> str:
        return prompt.instructions(learner)

    def __init__(self, learner: dict[str, Any], room: rtc.Room, board: dict[str, Any] | None = None,
                 greeting_note: str = "") -> None:
        # The greeting itself is fixed TTS spoken before the model's first turn; the note
        # tells the model it has greeted and carries the hints `greeting_instruction` gave.
        instructions = self._instructions(learner)
        if greeting_note:
            instructions += "\n\n" + greeting_note
        super().__init__(instructions=instructions)
        self.learner = learner
        board = board or {}
        self.board_w, self.board_h = clamp_board_size(board.get("w", DEFAULT_BOARD_W),
                                                     board.get("h", DEFAULT_BOARD_H))
        self.board_device = str(board.get("device", "desktop"))[:20]
        self.room = room
        self.ids = Ids()
        self.boards: dict[str, HtmlItem] = {}
        self._board_render_lock = asyncio.Lock()
        self.current_board_id: str | None = None
        self.child_identity: str | None = None
        self.mode = "talking"
        self.notes_saved = 0
        self._http: aiohttp.ClientSession | None = None

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
        Drawing runs in the background: keep helping the child in words while it
        draws. Do not describe the unseen board or request another drawing. The
        finished result arrives with a note and screenshot: look at both, then teach from what
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
        if self._board_render_lock.locked():
            return BOARD_IN_PROGRESS
        async with self._board_render_lock:
            await context.update(BOARD_STARTED)
            return await self._commission_board(need, background, title)

    async def _commission_board(self, need: str, background: str, title: str) -> str:
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
        controls are preserved), then replaces the same id in place. Keep helping
        in words while it draws. Teach from the screenshot when the finished
        result arrives, as its author.

        Args:
            changes: What should change, e.g. "Make the clock show half past
                instead, keep everything else the same".
            board_id: Which saved board to edit, e.g. "b1". Omit to edit the
                most recent board.
        """
        if self._board_render_lock.locked():
            return BOARD_IN_PROGRESS
        async with self._board_render_lock:
            return await self._edit_board(context, changes, board_id)

    async def _edit_board(self, context: RunContext, changes: str, board_id: str) -> str:
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
        await context.update(BOARD_STARTED)
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

        Only after some teaching has happened, never at the greeting or before the
        child has worked on anything.

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


class SmartTutor(Tutor):
    """The tutor in smart-screen mode (``TUTOR_SCREEN=smart``).

    The Screen agent next to it renders pages in the background; this tutor
    asks for them with ``ask_screen`` and brings them in with ``show_page``,
    ``reveal`` and ``point``. ``commission_board``/``edit_board`` are gone.
    """

    commission_board = None
    edit_board = None

    @staticmethod
    def _instructions(learner: dict[str, Any]) -> str:
        return prompt.smart_instructions(learner)

    def __init__(self, learner: dict[str, Any], room: rtc.Room,
                 board: dict[str, Any] | None = None, screen: Any = None,
                 greeting_note: str = "") -> None:
        if screen is None:
            raise ValueError("SmartTutor needs a Screen")
        self.screen = screen
        super().__init__(learner, room, board=board, greeting_note=greeting_note)
        # The Screen renders at the pane size the tutor keeps current.
        screen.set_pane_source(lambda: (self.board_w, self.board_h))

    @function_tool()
    async def ask_screen(self, context: RunContext, ask: str) -> str:
        """Ask the screen for a new page or a change to the visible one.

        Ask in terms of what the child needs right now (who they are, what was
        just said, what should land); the screen hears the whole lesson, so one
        short ask is enough. Returns at once: keep talking with the child in
        words while it works. Never announce a wait or describe the unseen page.
        A finished page stays invisible until you call show_page; a change to
        the visible page applies by itself and arrives with a note.

        Args:
            ask: What the child needs, e.g. "En sida om klockan halv sju för åk 1".
        """
        job = self.screen.ask(ask)
        return ("The screen is working on it now "
                f"(job {job}). Keep talking with the child in words: explain, ask, "
                "or react to what they just said. Do not announce a wait. "
                "A finished page stays invisible until you call show_page with its id; "
                "a change to the visible page applies by itself.")

    @function_tool()
    async def show_page(self, context: RunContext, page_id: str) -> str:
        """Put a finished screen page in front of the child.

        Args:
            page_id: Which finished page, e.g. "p1" (from the ready note).
        """
        page = self.screen.page((page_id or "").strip())
        if page is None:
            known = ", ".join(sorted(self.screen.pages)) or "none yet"
            return (f"Unknown page id '{page_id}'. Finished pages: {known}. "
                    "No page was shown. Explain in words instead, briefly.")
        try:
            item = PageItem(id=page.page_id, title=page.title, body=page.body)
        except ValidationError:
            return (f"Page {page.page_id} is too large to show. "
                    "Explain in words instead, briefly.")
        shown = await self._rpc("board.show", item.model_dump(exclude_none=True))
        if not shown:
            return (f"Page {page.page_id} could not be shown. "
                    "Explain in words instead, briefly.")
        self.screen.mark_visible(page.page_id)
        return (f"Page {page.page_id} is now visible. "
                "Teach from what it actually shows, as its author.")

    @function_tool()
    async def reveal(self, context: RunContext, part_id: str) -> str:
        """Uncover a hidden answer or a `later` part on the visible page.

        Args:
            part_id: The part's id from the page source, e.g. "facit".
        """
        part = (part_id or "").strip()
        if not part:
            return "No part given. Nothing was revealed."
        if self.screen.visible_id is None:
            return "No page is on screen yet. Nothing was revealed."
        ok = await self._rpc("board.reveal", {"id": self.screen.visible_id, "part": part})
        if not ok:
            return f"Part {part} could not be revealed. Explain in words instead, briefly."
        return f"Part {part} is now visible. Talk about what it shows."

    @function_tool()
    async def point(self, context: RunContext, part_id: str) -> str:
        """Highlight one part of the visible page.

        Args:
            part_id: The part's id from the page source, e.g. "steg-2".
        """
        part = (part_id or "").strip()
        if not part:
            return "No part given. Nothing was highlighted."
        if self.screen.visible_id is None:
            return "No page is on screen yet. Nothing was highlighted."
        ok = await self._rpc("board.point", {"id": self.screen.visible_id, "part": part})
        if not ok:
            return f"Part {part} could not be highlighted. Explain in words instead, briefly."
        return f"Part {part} is highlighted. Talk about it."

    async def _prompt_when_free(self, session: AgentSession, text: str) -> None:
        """Prompt the tutor once it is not speaking; while it (or the child)
        is speaking, wait for that speech to finish first (bounded)."""
        try:
            for _ in range(100):
                if session.agent_state != "speaking" and session.user_state != "speaking":
                    break
                await asyncio.sleep(0.3)
        except Exception:
            pass
        prompt_event(session, text)

    async def screen_page_ready(self, session: AgentSession, page: Any) -> None:
        """A new page finished: add it to the context invisible, then prompt once."""
        parts: list[Any] = []
        if getattr(page, "png", None):
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(page.png).decode()}",
                inference_detail="high"))
        text = (f"[Screen page {page.page_id} ('{page.title}') is ready but NOT visible. "
                f"Source:\n{page.body}\nCall show_page('{page.page_id}') when it fits "
                f"the lesson.]")
        record_active("screen_ready", {"page": page.page_id, "title": page.title,
                                           "image": bool(getattr(page, 'png', None))})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)
        asyncio.create_task(self._prompt_when_free(
            session, f"Screen page {page.page_id} ('{page.title}') is ready but not visible. "
                      f"If it fits the lesson now, call show_page('{page.page_id}'); "
                      f"otherwise keep teaching and bring it in later."))

    async def screen_patch_ready(self, session: AgentSession, patch: Any) -> None:
        """A change finished: apply it at once, add it to the context, no prompt."""
        ok = await self._rpc("board.patch", {"id": patch.page_id, "patch": patch.patch})
        parts: list[Any] = []
        if getattr(patch, "png", None):
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(patch.png).decode()}",
                inference_detail="high"))
        applied = "applied on the visible page" if ok else "could NOT be applied"
        text = (f"[Screen change {applied} (page {patch.page_id}). "
                f"Patch source:\n{patch.patch}\nThe screenshot shows the page now.]")
        record_active("screen_patched", {"page": patch.page_id, "ok": ok})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)

    async def screen_failed(self, session: AgentSession, message: str) -> None:
        """A screen job failed: tell the tutor and let it say so once it is free.

        Quiet failure left the child waiting in silence (2026-11-13: 26 s until
        the child asked "Hur går det?")."""
        record_active("screen_failed", {"message": message[:200]})
        await self._prompt_when_free(
            session,
            f"The screen failed: {message} Tell the child in one short sentence that "
            "the picture did not work, and carry on teaching in words.")


def prompt_event(session: AgentSession, text: str):
    """Ask for a reply to something that happened in the session (not speech).

    Sent as a bracketed user-role event: some OpenAI-compatible endpoints reject a
    request whose only new content is a system instruction or that ends on the
    model's own turn.
    """
    return session.generate_reply(user_input=f"[Session event, not the child's words: {text}]")


def is_fatal_llm_error(event: Any) -> bool:
    """A provider error LiveKit will not retry (for example an HTTP 400).

    LiveKit emits these as an LLMError with `recoverable=False` and leaves the turn
    unanswered. The turn's user message stays in history, so the child waits in
    silence and every later request may fail the same way.
    """
    error = getattr(event, "error", None)
    return getattr(error, "type", None) == "llm_error" and getattr(
        error, "recoverable", None
    ) is False


# Spoken without the LLM, because the LLM is what failed. One short sentence; the room
# is deleted afterwards, so the browser shows its disconnected notice with a restart button.
PROVIDER_FAILED_APOLOGY = (
    "Förlåt, jag fick ett tekniskt problem och kan inte fortsätta just nu. "
    "Stäng fönstret och starta en ny session, så försöker vi igen."
)

# The child typed before the fixed greeting could play (see text_input.TypedChat): their
# message is answered with the greeting folded in, so the line is not spoken twice.
TYPED_BEFORE_GREETING = (
    'The child typed this before they heard you. Greet them by name in one short sentence, '
    'then answer what they wrote, in one reply. Your opening line was "{line}"; do not say '
    "all of it."
)


async def say_provider_failed(session: AgentSession) -> None:
    """Speak the apology through TTS only; never let this path raise."""
    record_active("provider_failed", {"apology": True})
    try:
        handle = session.say(PROVIDER_FAILED_APOLOGY, allow_interruptions=False)
        await asyncio.wait_for(handle.wait_for_playout(), timeout=20)
    except Exception as error:  # closing session, TTS down, or interrupted
        log.warning("could not say the provider-failure apology: %s", error)
        record_active("provider_failed", {"apology": False,
                                            "error": f"{type(error).__name__}"})


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
    # A misspelt TUTOR_NOISE_CANCELLATION must stop the worker at boot, not silently run
    # unfiltered while the operator believes the room is being cleaned.
    noise.noise_cancellation_mode()
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.5)
    warm_up()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    # Own the child's typed chat from the moment the room connects (see text_input.py):
    # a message that arrives before the handler exists is dropped by the RTC layer with
    # no record anywhere, and RoomIO only registers lk.chat when the session starts.
    typed = TypedChat()
    ctx.room.register_text_stream_handler(TOPIC_CHAT, typed.on_stream)
    child = await ctx.wait_for_participant()
    typed.expect(child.identity)
    try:
        meta = json.loads(child.metadata or "{}")
        learner = meta.get("learner", {})
        board = meta.get("board", {}) or {}
    except json.JSONDecodeError:
        learner = {}
        board = {}

    debug = DebugLog.create(ctx.room.name, learner, getattr(getattr(ctx, "job", None), "id", "?"))
    typed.attach_record(debug.record)

    # The greeting is fixed text through TTS, so the child hears the fox within about a
    # second no matter what the provider is doing. The model gets the line and the hints
    # `greeting_instruction` used to carry, so it does not greet again.
    greeting, greeting_variant = prompt.greeting_line(learner)
    note = prompt.greeting_note(learner, greeting)

    smart = os.environ.get("TUTOR_SCREEN") == "smart"
    screen = None
    if smart:
        from .screen import Screen, session_pages_dir
        screen = Screen(
            learner=learner,
            pages_dir=session_pages_dir(ctx.room.name, getattr(debug, "directory", None)),
            session_id=ctx.room.name,
        )
        tutor: Tutor = SmartTutor(learner, ctx.room, board=board, screen=screen, greeting_note=note)
        # The first screen job must not pay for the browser launch: start it
        # while the greeting still runs. The job path keeps its own fallback.
        asyncio.create_task(screen.warmup())
    else:
        tutor = Tutor(learner, ctx.room, board=board, greeting_note=note)
    tutor.child_identity = child.identity
    set_active(debug)

    voice = build_tts()
    log.info("tutor TTS route %s", tts_route(voice))
    # TUTOR_NOISE_CANCELLATION: off (default) | nc | bvc, applied to the child's inbound
    # audio before the VAD and the recogniser (noise.py).
    noise_mode = noise.noise_cancellation_mode()
    log.info("tutor noise cancellation %s", noise_mode)
    # TUTOR_FILLERS=1: a short fox sound when the reply is late (fillers.py). None when off.
    fillers = build_fillers(voice, delay=env_float("TUTOR_FILLER_AFTER_S", DEFAULT_FILLER_DELAY))
    llm_timeout = env_float("TUTOR_LLM_TIMEOUT_S", 5.0)
    session_llm = build_session_llm(ctx.room.name)
    session = AgentSession(
        stt=build_stt(),
        llm=session_llm,
        tts=voice,
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",
            endpointing={"min_delay": env_float("TUTOR_MIN_ENDPOINT", 0.6), "max_delay": 4.0},
            # TUTOR_INTERRUPT_MIN_S: how long sound must last before it stops the fox.
            # 0.4 s let room noise cut it off; the dev setup tries 2.0 (2026-11-13).
            interruption={"enabled": True, "mode": "vad",
                          "min_duration": env_float("TUTOR_INTERRUPT_MIN_S", 0.4)},
        ),
        # One retry on the same route, 5 s each: the child should not wait a minute for a
        # slow provider. A route that still fails is the failover's or the apology's job.
        conn_options=SessionConnectOptions(
            llm_conn_options=APIConnectOptions(
                timeout=llm_timeout, max_retry=1, retry_interval=LLM_RETRY_INTERVAL_S
            )
        ),
        max_tool_steps=6,
    )
    typed.attach_session(session)

    @session.on("conversation_item_added")
    def tutor_has_spoken(event) -> None:
        # After the first spoken turn a typed message no longer has to carry the greeting.
        item = getattr(event, "item", None)
        if getattr(item, "type", None) == "message" and getattr(item, "role", "") == "assistant":
            typed.mark_heard()

    @session.on("agent_state_changed")
    def tutor_speaking(event) -> None:
        if getattr(event, "new_state", None) == "speaking":
            typed.mark_heard()

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

    if fillers is not None:
        # Follows child turns and agent state; plays on its own track, never in the
        # chat context, the transcript or the caption.
        fillers.attach(session, lambda: tutor.mode)

    provider_failed = asyncio.Event()

    @session.on("error")
    def session_error(event) -> None:
        # Recorded by debug.record_sdk above (with the provider's message, see
        # debug_log._dump_error). A non-retryable one also ends the session below
        # instead of leaving the child waiting for a reply that cannot come.
        if is_fatal_llm_error(event):
            log.error("LLM error is not retryable; ending the session with an apology")
            provider_failed.set()

    if screen is not None:
        assert isinstance(tutor, SmartTutor)
        smart_tutor = tutor
        screen.on_page = lambda page: asyncio.create_task(
            smart_tutor.screen_page_ready(session, page))
        screen.on_patch = lambda patch: asyncio.create_task(
            smart_tutor.screen_patch_ready(session, patch))
        screen.on_failure = lambda message: asyncio.create_task(
            smart_tutor.screen_failed(session, message))

        @session.on("conversation_item_added")
        def forward_screen_turn(event) -> None:
            # Every conversation turn also goes to the Screen; worker-injected
            # session events ([Session event ...]) are not the child's words.
            item = getattr(event, "item", None)
            if getattr(item, "type", None) != "message":
                return
            role = getattr(item, "role", "")
            if role not in ("user", "assistant"):
                return
            try:
                text = item.text_content  # a property, not a method
            except Exception:
                return
            if not text or (role == "user" and text.startswith("[Session event")):
                return
            screen.add_turn("child" if role == "user" else "tutor", text)

    # ---- homework intake ----------------------------------------------------------
    pending: list[tuple[list[Any], str]] = []
    settle: asyncio.Task | None = None

    async def respond_to_homework() -> None:
        await asyncio.sleep(HOMEWORK_SETTLE)
        batch = list(pending)
        pending.clear()
        for parts, description in batch:
            await tutor.add_homework(parts, description)
            if screen is not None:
                screen.add_homework(description, [getattr(p, "image", None)
                                                  for p in parts if getattr(p, "image", None)])
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
        if event.get("type") == "mic":
            # The child (or a parent) pressed the microphone button.
            debug.record("mic", {"on": bool(event.get("on")), "why": str(event.get("why", ""))[:20]})
        elif event.get("type") == "end":
            ending.set()
        elif event.get("type") == "page-answer" and screen is not None:
            # Smart-screen mode: the child's answer from an answer box prompts a reply.
            page, part = str(event.get("page", ""))[:40], str(event.get("part", ""))[:40]
            value = str(event.get("value", ""))
            screen.record_answer(page, part, value, str(event.get("kind", "")))
            debug.record("prompt", {"kind": "page_answer", "page": page, "part": part})
            prompt_event(session, f"The child answered on page {page}, part {part}: "
                                   f"{value[:500]} Respond briefly to what they wrote.")
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

    ctx.room.register_byte_stream_handler("homework", spawn(on_homework_image))
    ctx.room.register_text_stream_handler("homework-text", spawn(on_homework_text))
    ctx.room.register_text_stream_handler("session-event", spawn(on_session_event))

    outcome = "unknown"
    warm_up_task: asyncio.Task | None = None

    def opening(_instruction: str) -> None:
        """The session is ready and nothing was typed before it: greet in fixed text.

        Synchronous on purpose. `TypedChat.start` calls this where it would otherwise
        prompt the LLM, so marking the greeting as heard here (rather than inside the
        task) closes the window in which a typed message would try to greet as well.
        """
        typed.mark_heard()
        asyncio.create_task(greet(session, debug, greeting, greeting_variant, learner))

    try:
        # The warm-up race runs during the greeting, so the choice is usually ready
        # before the child's first turn. It only exists when a second route is configured.
        if isinstance(session_llm, SessionLLM):
            warm_up_task = asyncio.create_task(
                session_llm.warm_up(instructions=tutor.instructions, tools=list(tutor.tools)),
                name="tutor-llm-warm-up",
            )
        await session.start(
            agent=tutor,
            room=ctx.room,
            # text_input=False: the worker owns lk.chat from connect time (see
            # text_input.py), so RoomIO must not take the topic over. audio_input carries
            # the noise-cancellation filter when one is configured.
            room_options=noise.room_options(child.identity, noise_mode),
            # TUTOR_CLOUD_RECORDING=1 uploads session audio and transcripts to LiveKit
            # Cloud observability. Off by default; the local debug log (TUTOR_DEBUG_LOG=1)
            # is the reviewable trail when Cloud is off or unreachable.
            record=os.environ.get("TUTOR_CLOUD_RECORDING") == "1",
        )
        debug.record("worker_session_started", {
            "cloud_recording": os.environ.get("TUTOR_CLOUD_RECORDING") == "1",
            "noise_cancellation": noise_mode})
        if fillers is not None:
            # Publishes the filler track and starts making the clips in the background;
            # a failure here leaves the feature off and never breaks the session.
            await fillers.start(ctx.room)
        await ctx.room.local_participant.set_attributes({"tutor.mode": "talking"})
        # TypedChat opens the session so a message typed before the room was ready is
        # answered instead of lost. With nothing queued it calls `opening`, which speaks
        # the fixed greeting through TTS alone; with a queued message that message is
        # answered with the greeting folded into one reply, so the line is not repeated.
        await typed.start(
            prompt.greeting_instruction(learner),
            opening,
            greet_instruction=TYPED_BEFORE_GREETING.format(line=greeting),
        )

        outcome = await _run_until_done(ctx, session, tutor, debug, ending, provider_failed)
    except Exception as error:
        outcome = f"error: {type(error).__name__}: {error}"[:300]
        log.exception("session failed")
        raise
    finally:
        if fillers is not None:
            await fillers.aclose()
        if warm_up_task is not None and not warm_up_task.done():
            warm_up_task.cancel()
        report_path = debug.finalize(outcome)
        if report_path is not None:
            log.info("debug session report: %s", report_path)
        clear_active()


async def greet(
    session: AgentSession, debug: DebugLog, greeting: str, variant: int, learner: dict[str, Any]
) -> None:
    """Speak the fixed greeting through TTS only; the LLM is not involved.

    `session.say` puts the line in the chat history as the assistant's turn, so the model
    knows it has greeted. The speech is interruptible as before: if the child talks or
    types during it, the greeting stops and their turn is answered as usual.
    """
    debug.record("greeting", {"kind": "fixed", "variant": variant, "text": greeting})
    try:
        # Not interruptible: on 2026-11-13 the microphone picked up room sound within a
        # second of joining in both of the owner's calls, which cancelled the greeting
        # before any audio and left about 11 s of silence. The line is short; speech
        # during it is answered when it ends.
        handle = session.say(greeting, allow_interruptions=False)
    except RuntimeError as error:
        # The session closed before the first word. Fall back to a generated greeting so
        # the child is never left in silence without an event in the log.
        log.warning("fixed greeting could not be spoken: %s", error)
        debug.record("greeting", {"kind": "generated", "why": "session not running"})
        debug.record("prompt", {"kind": "greeting"})
        prompt_event(session, prompt.greeting_instruction(learner))
        return

    async def wait_for_end() -> None:
        try:
            await handle.wait_for_playout()
            debug.record("greeting_done", {"interrupted": handle.interrupted})
        except Exception as error:  # closing session, TTS down, cancelled
            debug.record("greeting_done", {"ok": False, "error": type(error).__name__})

    asyncio.create_task(wait_for_end(), name="tutor-greeting")


async def _run_until_done(
    ctx: JobContext, session: AgentSession, tutor: Tutor, debug: DebugLog,
    ending: asyncio.Event, provider_failed: asyncio.Event | None = None,
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

    waits = [asyncio.create_task(ending.wait()), asyncio.create_task(left.wait()),
             asyncio.create_task(closed.wait())]
    if provider_failed is not None:
        waits.append(asyncio.create_task(provider_failed.wait()))
    await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    if provider_failed is not None and provider_failed.is_set() and not left.is_set():
        # The provider refused the turn and will not retry it. Say why without the LLM
        # and end; the 2026-11-06 note in safe_interrupt is the same lesson: a dead
        # provider must not leave the browser sitting in a silent room.
        outcome = "provider_error"
        await say_provider_failed(session)
    elif closed.is_set() and not ending.is_set() and not left.is_set():
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
