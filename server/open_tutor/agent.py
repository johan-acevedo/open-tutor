"""The tutor worker: one LiveKit agent session per learner session.

Run with `python -m open_tutor.agent start` (or `dev` while developing).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
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
from .locales import get_locale
from .analytics import SessionTracker, get_analytics, sanitize_outcome, stable_distinct_id
from .analytics import warm_up as warm_up_analytics
from .idle import IDLE_POLL_S, IdleWatch, idle_timeout_s
from .board import Ids, Note, PageItem, ResourceItem, youtube_embed
from .config import AGENT_NAME, DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, env_float
from .debug_log import DebugLog, clear_active, record_active, set_active
from .diag import parse_diag
from .dialogue_tts import DialogueTTS, is_dialogue_model
from .deepgram_tts import DeepgramFluxTTS, DEFAULT_MODEL as DEEPGRAM_DEFAULT_MODEL, parse_expressivity
from .session_llm import SessionLLM
from .page_answers import PageAnswers
from .text_input import TOPIC_CHAT, TypedChat
from .fillers import DEFAULT_DELAY_S as DEFAULT_FILLER_DELAY, build_fillers
from .tutor_llm import build_session_llm, warm_up
from .speech import speakable_stream, unspoken_stream

log = logging.getLogger("open-tutor")

BOARD_RPC_TIMEOUT = 6.0
# Worker → browser RPCs for the learner tools (set_learner_grade, switch_student).
# Acknowledged request/response: the tool returns only after the browser answers,
# so a failed call leaves the call exactly as it was. See docs/protocol.md.
LEARNER_RPC_TIMEOUT = 6.0
LEARNER_RPC_SET_NAME = "learner.setName"
LEARNER_RPC_SET_GRADE = "learner.setGrade"
LEARNER_RPC_SWITCH = "learner.switch"
HOMEWORK_SETTLE = 1.2  # seconds to wait for more PDF pages before responding
# Per LLM attempt. The default (10 s, three retries) is what made a slow provider keep a
# child waiting about 50 s for a greeting on 2026-11-14. One retry, then the failover in
# session_llm.py or the spoken apology at the end of this file.
LLM_RETRY_INTERVAL_S = 0.5

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


def screen_mode_notice(environ: dict[str, str] | None = None) -> str | None:
    """One warning, or nothing, for the retired ``TUTOR_SCREEN`` switch.

    The Smart Screen is the only mode (2026-11-18): the legacy card board is gone and
    the worker always builds the Screen. A deployment that still sets
    ``TUTOR_SCREEN=smart`` is exactly the running behaviour and stays silent; any other
    value is reported once per session instead of failing, so an old env file cannot
    stop a family call.
    """
    env = os.environ if environ is None else environ
    value = (env.get("TUTOR_SCREEN") or "").strip()
    if value and value != "smart":
        return f"TUTOR_SCREEN={value} is ignored: the Smart Screen is the only mode"
    return None


def is_valid_learner_name(name: Any) -> bool:
    """A first name worth storing: Unicode letters plus space, hyphen and
    apostrophe; 1-3 words; at most 40 chars; no digits or markup.

    The browser enforces the same rule before persisting (see
    web/src/learnerName.ts); the worker checks first so a misheard name is
    never sent for storage. On rejection the tool asks again and stores nothing."""
    if not isinstance(name, str):
        return False
    clean = " ".join(name.split())
    if not clean or len(clean) > 40:
        return False
    if re.search(r"\d", clean):
        return False
    words = clean.split(" ")
    if len(words) > 3:
        return False
    return all(re.fullmatch(r"[^\W_]+(?:['\u2019\-][^\W_]+)*", word) for word in words)


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
        # One serialized delivery path for every board change in the session:
        # shows, updates, removes, patches, reveals, points, resources and
        # loading states all go through _board_send, so no two changes
        # interleave on the way to the browser.
        self._board_lock = asyncio.Lock()
        self.child_identity: str | None = None
        self.mode = "talking"
        self.notes_saved = 0
        self._http: aiohttp.ClientSession | None = None
        # Set by the entrypoint: switch_student ends this lesson through it,
        # exactly like the browser's Avsluta event does.
        self.end_event: asyncio.Event | None = None

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
            ok = data.get("ok") is True
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

    async def _board_send(self, method: str, payload: dict[str, Any]) -> bool:
        """Send one board RPC; serialized with every other board change."""
        async with self._board_lock:
            return await self._rpc(method, payload)

    async def _show(self, item) -> str:
        shown = await self._board_send("board.show", item.model_dump(exclude_none=True))
        if not shown:
            return f"The board could not show item {item.id}. Explain in words instead, briefly."
        return f"Item {item.id} is now visible on the board. You can talk about it."

    # ---- resources ---------------------------------------------------------------

    @function_tool()
    async def find_resources(self, context: RunContext, query: str, videos: bool = True) -> str:
        """Search the public web for a short educational video or reading. Returns candidates.

        Only for videos and readings. Never for a picture, photo, painting or map image:
        those go to the screen with ask_screen.

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
        """Put one video or reading from find_resources on the board for the child to watch or read now.

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

    async def _learner_rpc(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """One acknowledged learner RPC to the browser; None when unanswered.

        The browser owns the profiles: it resolves the target in its serialized
        queue and answers, or rejects (stale target, unknown name). A failure
        leaves this call exactly as it was."""
        if not self.child_identity:
            return None
        try:
            reply = await self.room.local_participant.perform_rpc(
                destination_identity=self.child_identity,
                method=method,
                payload=json.dumps(payload, ensure_ascii=False),
                response_timeout=LEARNER_RPC_TIMEOUT,
            )
            data = json.loads(reply or "{}")
        except Exception as error:  # timeout, child left, or RPC rejection
            log.warning("learner rpc %s failed: %s", method, error)
            record_active("learner_rpc", {"method": method, "ok": False,
                                              "error": f"{type(error).__name__}"})
            return None
        if not isinstance(data, dict) or data.get("ok") is not True:
            record_active("learner_rpc", {"method": method, "ok": False})
            return None
        record_active("learner_rpc", {"method": method, "ok": True})
        return data

    @function_tool()
    async def set_learner_name(self, context: RunContext, name: str) -> str:
        """Save the learner's first name, so later calls start with it.

        Call it once, right after they tell you their name early in a nameless
        call: repeat the name back first to confirm you heard it. The browser
        creates the local profile, or attaches to an existing local profile
        with the same name (its school year and notes are then already known
        and come back in the acknowledgement). A later correction ("I said
        Noa, not Moa") is the same call again: a same-profile rename keeps
        its year and notes, while attaching to a different profile replaces
        them, including null/unknown. The call updates only on
        acknowledgement; a name that is not a name is rejected before anything
        is stored.

        Args:
            name: The learner's first name, as they said it.
        """
        clean = " ".join((name or "").split())
        if not is_valid_learner_name(clean):
            return ("That doesn't sound like a first name (letters only, up to three "
                    "words). Ask once more what they are called \u2014 they can "
                    "also type it in the text field \u2014 then call again.")
        data = await self._learner_rpc(LEARNER_RPC_SET_NAME,
                                       {"profileId": self.learner.get("id"), "name": clean})
        if data is None:
            return (f"The browser could not save the name {clean}, so nothing is saved. "
                    "Use it in this call anyway and mention nothing.")
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        new_id = profile.get("id", self.learner.get("id"))
        new_name = profile.get("name", clean)
        identity_changed = new_id != self.learner.get("id")
        name_changed = new_name != self.learner.get("name")
        self.learner["id"] = new_id
        self.learner["name"] = new_name
        if identity_changed:
            # A different profile owns this call now: its school year replaces
            # this call's, including null/unknown — keeping the old one would
            # teach to the wrong year. Its notes arrive in the acknowledgement,
            # the same context a returning start gets.
            grade = profile.get("grade")
            self.learner["grade"] = grade if isinstance(grade, int) and 1 <= grade <= 12 else None
            notes = profile.get("notes")
            if isinstance(notes, list):
                self.learner["notes"] = notes
        grade = self.learner.get("grade")
        known = ""
        if isinstance(grade, int) and 1 <= grade <= 12:
            known = (f" They are in \u00e5rskurs {grade}." if grade <= 9
                     else f" They are in gymnasiet, year {grade - 9}.")
        if identity_changed or name_changed:
            # NB: Tutor._instructions, not self._instructions — the LiveKit
            # base class stores the built prompt string under that name.
            await self.update_instructions(Tutor._instructions(self.learner))
        record_active("name", {"name": clean,
                                 "profile_id": self.learner.get("id")})
        return (f"Saved: the learner is called {clean}.{known} Use the name naturally "
                "from here on, and carry on with the lesson.")

    @function_tool()
    async def set_learner_grade(self, context: RunContext, grade: int) -> str:
        """Save the school year you just learned, so later calls start with it.

        Call it once, when the grade first becomes clear early in the call
        (asked naturally, or inferred from shared homework) — never at the
        greeting and never for adults (band 3). The browser applies it only
        when the profile is still this call's; the grade here updates only on
        acknowledgement.

        Args:
            grade: School year 1-9 (grundskolan) or 10-12 (gymnasiet year 1-3).
        """
        try:
            g = int(grade)
        except (TypeError, ValueError):
            return f"'{grade}' is not a school year. Use 1-12, or leave it unknown."
        if not 1 <= g <= 12:
            return f"'{grade}' is not a school year. Use 1-12, or leave it unknown."
        data = await self._learner_rpc(LEARNER_RPC_SET_GRADE,
                                       {"profileId": self.learner.get("id"), "grade": g})
        if data is None:
            return ("The browser could not store the school year, so nothing is saved. "
                    "Carry on with the lesson as before and mention nothing.")
        self.learner["grade"] = g
        record_active("grade", {"grade": g})
        return (f"Saved: the learner is in årskurs {g}. "
                "Keep this call's register as it is; later calls start with it.")

    @function_tool()
    async def switch_student(self, context: RunContext, name: str) -> str:
        """End this lesson; the next one starts with a different student.

        Only after confirming with them (and asking the name when it is new).
        The browser resolves or creates their profile and acknowledges with its
        id; this lesson then ends exactly like Avsluta (the note is saved, you
        say goodbye) and the start page opens prefilled for the new student —
        no automatic reconnect, no continuation session. A failed call leaves
        you with this student: say so briefly and carry on.

        Args:
            name: The new student's first name.
        """
        clean = (name or "").strip()[:40]
        if not clean:
            return "No name given. Ask who is there now, then call again."
        data = await self._learner_rpc(LEARNER_RPC_SWITCH, {"name": clean})
        if data is None:
            # The ack never arrived, so nothing was armed: carry on as A.
            current = str(self.learner.get("name") or "").strip() or "this student"
            record_active("switch_student", {"name": clean, "ok": False})
            return (f"Stay with {current}: the switch to {clean} did not go through. "
                    "Say so in one short sentence and carry on with the lesson.")
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
        record_active("switch_student", {"name": clean, "profile_id": profile.get("id")})
        # End A's lesson exactly like Avsluta; the goodbye comes through the
        # normal end path, and the browser then shows B's start page. Say nothing more.
        if self.end_event is not None:
            self.end_event.set()
        raise StopResponse()

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

    # ---- homework -----------------------------------------------------------------

    async def add_homework(self, parts: list[Any], description: str) -> None:
        record_active("homework_added", {"description": description[:300],
                                           "parts": len(parts),
                                           "image_parts": sum(1 for p in parts if hasattr(p, "image"))})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[f"[Shared homework: {description}]", *parts])
        await self.update_chat_ctx(ctx)


class SmartTutor(Tutor):
    """The live tutor: the base tutor plus the Smart Screen tools.

    The Screen agent next to it renders pages in the background; this tutor
    asks for them with ``ask_screen`` and brings them in with ``show_page``,
    ``reveal`` and ``point``. This is the only tutor mode the worker runs.
    """

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
    async def ask_screen(self, context: RunContext, ask: str, show: str = "auto") -> str:
        """Ask the screen for a new page or a change to the visible one.

        Ask in terms of what the child needs right now (who they are, what was
        just said, what should land); the screen hears the whole lesson, so one
        short ask is enough. Returns at once: keep talking with the child in
        words while it works. Never announce a wait or describe the unseen page.
        A finished page appears on the screen by itself as soon as it is ready
        (show="show", the default); pass show="hold" when the page must stay
        hidden until the child has tried, and bring it in later with show_page.
        When the child wants to see a real picture, photo, painting or map, say so
        in the ask: the screen finds and checks the image itself.
        A change to the visible page applies by itself and arrives with a note.

        Args:
            ask: What the child needs, e.g. "En sida om klockan halv sju för åk 1".
            show: "auto" (a finished page appears by itself), "show" (same),
                or "hold" (stays invisible until show_page).
        """
        mode = (show or "auto").strip().lower()
        if mode == "auto":
            mode = "show"
        if mode not in ("show", "hold"):
            return (f"Unknown show mode '{show}'. Use show=\"show\" (the page appears "
                    "by itself) or show=\"hold\" (it stays hidden until show_page). "
                    "Nothing was asked.")
        job = self.screen.ask(ask, reveal=mode)
        if mode == "show":
            return ("The screen is working on it now "
                    f"(job {job}). Keep talking with the child in words: explain, ask, "
                    "or react to what they just said. Do not announce a wait. "
                    "The finished page appears on the screen by itself as soon as it is "
                    "ready; you get its source and a screenshot then.")
        return ("The screen is working on it now "
                f"(job {job}). Keep talking with the child in words: explain, ask, "
                "or react to what they just said. Do not announce a wait. "
                "A finished page stays invisible until you call show_page with its id; "
                "a change to the visible page applies by itself.")

    @function_tool()
    async def show_page(self, context: RunContext, page_id: str) -> str:
        """Put a finished screen page in front of the child.

        Only needed for a page asked with show="hold"; other pages appear by
        themselves. Calling it again for the page already on screen is harmless.

        Args:
            page_id: Which finished page, e.g. "p1" (from the ready note).
        """
        page = self.screen.page((page_id or "").strip())
        if page is None:
            known = ", ".join(sorted(self.screen.pages)) or "none yet"
            return (f"Unknown page id '{page_id}'. Finished pages: {known}. "
                    "No page was shown. Explain in words instead, briefly.")
        ok, note = await self._show_page_object(page)
        return note

    async def _show_page_object(self, page: Any) -> tuple[bool, str]:
        """Deliver one finished page object to the browser (shared by the
        show_page tool and the show-when-ready path in screen_page_ready)."""
        try:
            item = PageItem(id=page.page_id, title=page.title, body=page.body)
        except ValidationError:
            return (False, f"Page {page.page_id} is too large to show. "
                    "Explain in words instead, briefly.")
        async with self._board_lock:
            shown = await self._rpc("board.show", item.model_dump(exclude_none=True))
            if not shown:
                return (False, f"Page {page.page_id} could not be shown. "
                        "Explain in words instead, briefly.")
            self.screen.mark_visible(page.page_id)
        return (True, f"Page {page.page_id} is now visible. "
                "Teach from what it actually shows, as its author.")

    @function_tool()
    async def screen_loading(self, context: RunContext, topic: str) -> str:
        """Dim the visible page and show "Laddar <topic>…" at once.

        Call it when you move to a new subject, so the child never reads the
        old page while you talk about the new one. It clears by itself when new
        content arrives; call with an empty topic to clear it sooner.

        Args:
            topic: The new subject in Swedish, e.g. "historia"; empty clears.
        """
        topic = (topic or "").strip()[:120]
        if self.screen.visible_id is None:
            return "No page is on screen yet. Nothing was dimmed."
        ok = await self._board_send("board.loading",
                                    {"id": self.screen.visible_id, "topic": topic})
        if not ok:
            return ("The loading state could not be shown. "
                    "Keep teaching in words instead, briefly.")
        if topic:
            template = get_locale(prompt.learner_locale(self.learner)).LOADING_TEMPLATE
            shown = template.format(topic=topic)
            return (f"The screen is dimmed and shows '{shown}'. "
                    "Keep talking about the new subject in words until its page appears.")
        return "The loading state is cleared."

    @function_tool()
    async def screen_status(self, context: RunContext) -> str:
        """Ask what the screen is doing right now.

        One cheap line: writing, pictures, checking, ready or shown, and how
        long it has been there. Call it when the wait grows long or the child
        asks how the page is going; tell the child in one short Swedish
        sentence, then keep teaching in words.
        """
        return self.screen.status_line()

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
        ok = await self._board_send("board.reveal", {"id": self.screen.visible_id, "part": part})
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
        ok = await self._board_send("board.point", {"id": self.screen.visible_id, "part": part})
        if not ok:
            return f"Part {part} could not be highlighted. Explain in words instead, briefly."
        return f"Part {part} is highlighted. Talk about it."

    async def _prompt_when_free(self, session: AgentSession, text: str) -> None:
        """Prompt the tutor once it is not speaking; while it (or the child)
        is speaking, wait for that speech to finish first (bounded)."""
        await wait_until_free(session)
        prompt_event(session, text)

    async def _clear_loading(self, page_id: str | None = None) -> bool:
        """Clear a loading veil best-effort; True when the RPC went out.

        Terminal job states (held page ready, failed job, replaced page) must
        never leave a stale \"Laddar …\" on screen: the fox reveals a held
        page when it wants, so the veil's job is done."""
        target = page_id or (self.screen.visible_id if self.screen else None)
        if target is None:
            return False
        try:
            return await self._board_send("board.loading", {"id": target, "topic": ""})
        except Exception:  # noqa: BLE001 - clearing is best-effort
            return False

    async def screen_page_ready(self, session: AgentSession, page: Any) -> None:
        """A new page finished: show it at once, or hold it when asked.

        The default reveal mode (``ask_screen`` without ``show="hold"``) puts
        the page in front of the child immediately, so a new subject never
        waits behind the old page until the tutor's next turn. A held page
        keeps the old behaviour: added to the context invisible, then one
        prompt once the tutor is free."""
        parts: list[Any] = []
        if getattr(page, "png", None):
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(page.png).decode()}",
                inference_detail="high"))
        if getattr(page, "reveal", "show") == "show":
            old_id = self.screen.visible_id
            ok, note = await self._show_page_object(page)
            if ok:
                if old_id is not None and old_id != page.page_id:
                    # The old frame stays mounted for back-navigation: do not
                    # leave its veil on.
                    await self._clear_loading(old_id)
                text = (f"[Screen page {page.page_id} ('{page.title}') is now ON SCREEN. "
                        f"Source:\n{page.body}\nTeach from what it actually shows.]")
                record_active("screen_ready", {"page": page.page_id, "title": page.title,
                                                   "image": bool(getattr(page, 'png', None)),
                                                   "shown": True})
                ctx = self.chat_ctx.copy()
                ctx.add_message(role="user", content=[text, *parts])
                await self.update_chat_ctx(ctx)
                asyncio.create_task(self._prompt_when_free(
                    session, f"Screen page {page.page_id} ('{page.title}') is on screen now. "
                              f"Teach from what it actually shows."))
                return
            # Auto-show failed: fall through to the held path so the tutor
            # still gets the page and can bring it in with show_page.
            text = (f"[Screen page {page.page_id} ('{page.title}') is ready but NOT visible "
                    f"(it could not be shown by itself: {note}). "
                    f"Source:\n{page.body}\nCall show_page('{page.page_id}') when it fits "
                    f"the lesson.]")
        else:
            text = (f"[Screen page {page.page_id} ('{page.title}') is ready but NOT visible. "
                    f"Source:\n{page.body}\nCall show_page('{page.page_id}') when it fits "
                    f"the lesson.]")
        # Terminal state: the veil's job is done whether the page shows now
        # or the fox brings it in later with show_page.
        await self._clear_loading()
        record_active("screen_ready", {"page": page.page_id, "title": page.title,
                                           "image": bool(getattr(page, 'png', None))})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)
        asyncio.create_task(self._prompt_when_free(
            session, f"Screen page {page.page_id} ('{page.title}') is ready but not visible. "
                      f"If it fits the lesson now, call show_page('{page.page_id}'); "
                      f"otherwise keep teaching and bring it in later."))

    async def screen_patch_ready(self, session: AgentSession, patch: Any) -> bool:
        """A change finished: apply it at once, add it to the context, no prompt.

        Sent through the serialized delivery path, like every other board
        change. Returns whether the change was sent, so the Screen only
        records delivered patches in its history."""
        parts: list[Any] = []
        if getattr(patch, "png", None):
            parts.append(llm.ImageContent(
                image=f"data:image/png;base64,{base64.b64encode(patch.png).decode()}",
                inference_detail="high"))
        ok = await self._board_send("board.patch", {"id": patch.page_id, "patch": patch.patch})
        applied = "applied on the visible page" if ok else "could NOT be applied"
        text = (f"[Screen change {applied} (page {patch.page_id}). "
                f"Patch source:\n{patch.patch}\nThe screenshot shows the page now.]")
        record_active("screen_patched", {"page": patch.page_id, "ok": ok})
        ctx = self.chat_ctx.copy()
        ctx.add_message(role="user", content=[text, *parts])
        await self.update_chat_ctx(ctx)
        return ok

    async def screen_failed(self, session: AgentSession, message: str) -> None:
        """A screen job failed: tell the tutor and let it say so once it is free.

        Quiet failure left the child waiting in silence (2026-11-13: 26 s until
        the child asked "Hur går det?"). A loading overlay from screen_loading
        is cleared best-effort first, so no stale "Laddar …" stays on screen."""
        await self._clear_loading()
        record_active("screen_failed", {"message": message[:200]})
        await self._prompt_when_free(
            session,
            f"The screen failed: {message} Tell the child in one short sentence that "
            "the picture did not work, and carry on teaching in words.")


async def wait_until_free(session: Any, *, poll_s: float = 0.3, max_polls: int = 100) -> None:
    """Return once neither the tutor nor the child is speaking (bounded, ~30 s).

    A generate_reply while the tutor speaks cuts its sentence off."""
    try:
        for _ in range(max_polls):
            if session.agent_state != "speaking" and session.user_state != "speaking":
                return
            await asyncio.sleep(poll_s)
    except Exception:  # noqa: BLE001 - a missing state never blocks the prompt
        return


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
# Fixed lines live in server/open_tutor/locales/sv.py; this alias keeps the
# previous import path working. The worker picks the session locale at runtime.
from .locales.sv import PROVIDER_FAILED_APOLOGY

# The child typed before the fixed greeting could play (see text_input.TypedChat): their
# message is answered with the greeting folded in, so the line is not spoken twice.
TYPED_BEFORE_GREETING = (
    'The child typed this before they heard you. Greet them by name in one short sentence, '
    'then answer what they wrote, in one reply. Your opening line was "{line}"; do not say '
    "all of it."
)

# Voice-first start: the call began with no name, so the folded-in greeting asks for
# it instead of using one.
TYPED_BEFORE_GREETING_NAMELESS = (
    'The child typed this before they heard you. Greet them warmly in one short sentence '
    'without using any name (you do not know it yet), ask what they are called, '
    'then answer what they wrote, in one reply. Your opening line was "{line}"; do not say '
    "all of it."
)


async def say_idle_goodbye(session: AgentSession, locale: str = "sv") -> None:
    """Speak the idle line through TTS only; never let this path raise.

    Said after a long learner silence before the call ends itself (idle.py).
    Like the provider apology, the LLM is not involved."""
    record_active("idle_goodbye", {})
    try:
        await wait_until_free(session)
        line = get_locale(locale).IDLE_GOODBYE
        handle = session.say(line, allow_interruptions=True)
        await asyncio.wait_for(handle.wait_for_playout(), timeout=20)
        debug_note = {"interrupted": handle.interrupted}
    except Exception as error:  # closing session, TTS down, or interrupted
        log.warning("could not say the idle goodbye: %s", error)
        debug_note = {"ok": False, "error": f"{type(error).__name__}"}
    record_active("idle_goodbye_done", debug_note)


async def say_provider_failed(session: AgentSession, locale: str = "sv") -> None:
    """Speak the apology through TTS only; never let this path raise."""
    record_active("provider_failed", {"apology": True})
    try:
        apology = get_locale(locale).PROVIDER_FAILED_APOLOGY
        handle = session.say(apology, allow_interruptions=False)
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


def warm_provider_connections() -> None:
    """Open one connection to each configured provider, bounded and never failing.

    After a cold restart the first real request can stall (seen 2026-11-14: Go
    did not answer the 5 s warm-up right after a restart, then was normal a
    minute later). Warming DNS/TCP/TLS here moves that cost to worker start.
    Provider keys stay in the backend environment and are never logged."""
    import os

    from .http_clients import warm_provider_connections as warm
    from .screen import (
        COMMAND_CODE_BASE_URL,
        GEMINI_BASE_URL,
        SCREEN_BASE_URL,
        _spec_provider,
        default_fallback_spec,
        default_model_spec,
    )
    from .config import USER_AGENT, llm_fallback_route, llm_route

    base_urls = {"cc": COMMAND_CODE_BASE_URL, "google": GEMINI_BASE_URL, "go": SCREEN_BASE_URL}
    key_names = {"cc": "COMMAND_CODE_API_KEY", "google": "GEMINI_API_KEY", "go": "OPENCODE_GO_API_KEY"}
    routes: list[tuple[str, str, str]] = []
    try:
        preferred = llm_route()
        routes.append((f"tutor:{preferred.name}", preferred.base_url, preferred.api_key))
        fallback = llm_fallback_route()
        if fallback is not None:
            routes.append((f"tutor:{fallback.name}", fallback.base_url, fallback.api_key))
    except Exception as error:  # noqa: BLE001 - missing keys at prewarm: still try the screen
        log.debug("tutor provider warm-up skipped its routes: %s", error)
    try:
        specs = [default_model_spec()]
        fallback_spec = default_fallback_spec()
        if fallback_spec is not None:
            specs.append(fallback_spec)
        for spec in specs:
            provider = _spec_provider(spec)
            key = os.environ.get(key_names.get(provider, "OPENCODE_GO_API_KEY"), "")
            if key:
                routes.append((f"screen:{spec['model']}",
                               base_urls.get(provider, SCREEN_BASE_URL), key))
    except Exception as error:  # noqa: BLE001 - a bad SCREEN_* value must not stop the worker
        log.debug("screen provider warm-up skipped its specs: %s", error)
    warm(routes, USER_AGENT)


def prewarm(proc: JobProcess) -> None:
    # A misspelt TUTOR_NOISE_CANCELLATION must stop the worker at boot, not silently run
    # unfiltered while the operator believes the room is being cleaned. A configured
    # filter then loads its native side here: on 2026-11-14 the first import inside a
    # session blocked the loop for about a second and pushed the greeting back.
    noise.warm_up(noise.noise_cancellation_mode())
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.5)
    warm_up()
    # The first analytics capture inside a session blocked the loop importing the
    # SDK; with a key set this moves that import to worker start. Without a key it
    # imports nothing and analytics stays fully off.
    warm_up_analytics()
    # Open one connection per configured provider (tutor routes plus the screen
    # specs): bounded to ~5 s, never failing the worker.
    warm_provider_connections()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    # Own the child's typed chat from the moment the room connects (see text_input.py):
    # a message that arrives before the handler exists is dropped by the RTC layer with
    # no record anywhere, and RoomIO only registers lk.chat when the session starts.
    typed = TypedChat()
    # Typed turns are counted at the typed-input boundary, not from SDK chat
    # items (spoken transcripts arrive there too and would double-count). The
    # listener attaches before the stream handler exists, so a message typed
    # while we wait for the participant is still counted.
    tracker = SessionTracker()
    typed.attach_typed_listener(tracker.record_typed_turn)
    # The idle-silence clock (idle.py): generous, only a forgotten open tab
    # trips it. Created here so every handler below can close over it.
    idle = IdleWatch(idle_timeout_s())
    idle_ended = asyncio.Event()
    # A typed message is learner activity, like speech: attach next to the
    # counter above (TypedChat supports several listeners).
    typed.attach_typed_listener(idle.note_activity)
    ctx.room.register_text_stream_handler(TOPIC_CHAT, typed.on_stream)
    child = await ctx.wait_for_participant()
    typed.expect(child.identity)
    try:
        meta = json.loads(child.metadata or "{}")
        learner = meta.get("learner", {})
        board = meta.get("board", {}) or {}
        device_id = meta.get("device_id")
    except json.JSONDecodeError:
        learner = {}
        board = {}
        device_id = None

    debug = DebugLog.create(ctx.room.name, learner, getattr(getattr(ctx, "job", None), "id", "?"))
    typed.attach_record(debug.record)

    # The greeting is fixed text through TTS, so the child hears the fox within about a
    # second no matter what the provider is doing. The model gets the line and the hints
    # `greeting_instruction` used to carry, so it does not greet again.
    greeting, greeting_variant = prompt.greeting_line(learner)
    note = prompt.greeting_note(learner, greeting)

    notice = screen_mode_notice()
    if notice:
        log.warning(notice)
    from .screen import Screen, session_pages_dir

    screen = Screen(
        learner=learner,
        pages_dir=session_pages_dir(ctx.room.name, getattr(debug, "directory", None)),
        session_id=ctx.room.name,
    )
    tutor = SmartTutor(learner, ctx.room, board=board, screen=screen, greeting_note=note)
    # The first screen job must not pay for the browser launch: start it
    # while the greeting still runs. The job path keeps its own fallback.
    asyncio.create_task(screen.warmup())
    tutor.child_identity = child.identity
    # Created here, not next to on_session_event below: switch_student ends
    # this lesson through it, and the tutor exists before that definition.
    ending = asyncio.Event()
    tutor.end_event = ending
    set_active(debug)

    # Product analytics (PostHog): one process-wide client, fully off without
    # TUTOR_POSTHOG_KEY. Bound here, before any handler registration below
    # closes over the tracker: Python reads enclosing-function locals at call
    # time, but these are entrypoint locals, so a later assignment would be
    # an UnboundLocalError in every session, analytics on or off.
    analytics = get_analytics()
    # The learner's name is never part of the id: children's names stay out
    # of analytics entirely (see analytics.stable_distinct_id).
    distinct_id = stable_distinct_id(device_id, ctx.room.name)

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
        tracker.record_sdk(event)

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
        session.on(sdk_event, tracker.record_sdk)
    # Any transcript, final or interim, is the learner speaking: restart the
    # idle-silence clock. Tutor speech alone never touches it (see idle.py).
    session.on("user_input_transcribed", lambda _event: idle.note_activity())
    # "close" has its own debug subscription in _run_until_done (session_closed)
    # and "function_tools_executed" its own handler above: both record to the
    # tracker here so the ended-event counts match the debug summary.
    session.on("close", tracker.record_sdk)

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

    screen.on_page = lambda page: asyncio.create_task(
        tutor.screen_page_ready(session, page))
    screen.on_patch = lambda patch: asyncio.create_task(
        tutor.screen_patch_ready(session, patch))
    screen.on_failure = lambda message: asyncio.create_task(
        tutor.screen_failed(session, message))

    async def note_page_answer(text: str) -> None:
        ctx_ = tutor.chat_ctx.copy()
        ctx_.add_message(role="user", content=[text])
        await tutor.update_chat_ctx(ctx_)

    page_answers = PageAnswers(
        prompt=lambda text: prompt_event(session, text),
        note=note_page_answer, record=debug.record,
        wait_free=lambda: wait_until_free(session))
    # An answer still waiting for its turn must not reply into a closed session.
    session.on("close", lambda _event: page_answers.close())

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
        if role == "user":
            page_answers.child_spoke(text)
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
        idle.note_activity()
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
        idle.note_activity()
        text = (await reader.read_all())[:12000]
        attrs = dict(reader.info.attributes or {})
        description = f"pasted text (board id {attrs.get('itemId', '?')})"
        debug.record("homework_shared", {"kind": "text", "description": description,
                                           "chars": len(text), "text": text})
        pending.append(([text], description))
        schedule_reply()

    async def on_session_event(reader: rtc.TextStreamReader, identity: str) -> None:
        try:
            event = json.loads(await reader.read_all())
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "diag":
            # Sequenced browser diagnostics: keep only the normalized batch.
            # The debug log stamps server receive time; seq/dropped expose
            # what never made it off the page.
            parsed = parse_diag(event)
            if parsed is None:
                debug.record("browser_event", {"type": "diag-rejected"})
                return
            debug.record("diag", parsed)
            return
        debug.record("browser_event", {"type": str(event.get("type", "?"))[:40]})
        # Learner activity for the idle-silence clock: a mic-button press, a
        # page answer, or closing a resource. (board-size reports layout
        # resizes on its own and diag is diagnostics: neither is activity.)
        if event.get("type") in ("mic", "page-answer", "resource-closed"):
            idle.note_activity()
        if event.get("type") == "mic":
            # The child (or a parent) pressed the microphone button.
            debug.record("mic", {"on": bool(event.get("on")), "why": str(event.get("why", ""))[:20]})
        elif event.get("type") == "end":
            ending.set()
        elif event.get("type") == "page-answer":
            # The child's answer from an answer box on a page prompts a reply.
            page, part = str(event.get("page", ""))[:40], str(event.get("part", ""))[:40]
            value = str(event.get("value", ""))
            screen.record_answer(page, part, value, str(event.get("kind", "")))
            page_answers.add(page, part, value)
        elif event.get("type") == "board-size":
            # The browser measures the real board pane (ResizeObserver) and
            # reports resizes/rotation mid-session; the Screen renders at it.
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
    idle_task: asyncio.Task | None = None

    async def watch_idle() -> None:
        """End the call after long learner silence (idle.py).

        Polls, never fires while the tutor is mid-speech (the check simply
        waits for a quiet moment), and does nothing when disabled. Wakes
        _run_until_done through idle_ended, which then takes the normal
        ending path with the idle_timeout outcome."""
        if not idle.enabled:
            return
        while True:
            await asyncio.sleep(min(IDLE_POLL_S, idle.timeout_s))
            # Either side mid-speech defers the check: a learner who just
            # started talking is not idle even before the transcript lands.
            try:
                speaking = (session.agent_state == "speaking"
                            or session.user_state == "speaking")
            except Exception:
                speaking = False
            if idle.expired(speaking=speaking):
                record_active("idle_timeout", {
                    "silent_s": round(idle.seconds_since_activity(), 1)})
                idle_ended.set()
                return

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
        # The silence clock starts with the session: greeting and setup count
        # as quiet only until the learner first speaks, types or shares.
        idle_task = asyncio.create_task(watch_idle(), name="tutor-idle-watch")
        analytics.capture(distinct_id, "tutor_session_started", {
            "room": ctx.room.name,
            "grade": learner.get("grade"),
            "returning": len(learner.get("notes") or []) > 0,
            "llm_route": os.environ.get("TUTOR_LLM", "go"),
            "tts": tts_route(voice),
        })
        if fillers is not None:
            # Publishes the filler track and starts making the clips in the background;
            # a failure here leaves the feature off and never breaks the session.
            await fillers.start(ctx.room)
        await ctx.room.local_participant.set_attributes({"tutor.mode": "talking"})
        # TypedChat opens the session so a message typed before the room was ready is
        # answered instead of lost. With nothing queued it calls `opening`, which speaks
        # the fixed greeting through TTS alone; with a queued message that message is
        # answered with the greeting folded into one reply, so the line is not repeated.
        typed_greeting = (TYPED_BEFORE_GREETING_NAMELESS if not prompt.learner_name(learner)
                          else TYPED_BEFORE_GREETING)
        await typed.start(
            prompt.greeting_instruction(learner),
            opening,
            greet_instruction=typed_greeting.format(line=greeting),
        )

        outcome = await _run_until_done(ctx, session, tutor, debug, ending, provider_failed,
                                        idle_done=idle_ended)
    except Exception as error:
        outcome = f"error: {type(error).__name__}: {error}"[:300]
        log.exception("session failed")
        raise
    finally:
        if idle_task is not None and not idle_task.done():
            idle_task.cancel()
        if fillers is not None:
            await fillers.aclose()
        if warm_up_task is not None and not warm_up_task.done():
            warm_up_task.cancel()
        report_path = debug.finalize(outcome)
        if report_path is not None:
            log.info("debug session report: %s", report_path)
        try:
            summary = tracker.summary()
            # Fixed category only: the raw outcome can carry an exception
            # message, which never leaves the worker (see sanitize_outcome).
            outcome_category, error_type = sanitize_outcome(outcome)
            ended: dict[str, Any] = {
                "room": ctx.room.name,
                "duration_s": round(time.time() - debug.started_at, 1),
                "outcome": outcome_category,
                "close_reason": summary.get("close_reason"),
                "child_spoken_turns": summary.get("child_final_turns", 0),
                "child_typed_turns": summary.get("child_typed_turns", 0),
                "tutor_replies": summary.get("tutor_replies", 0),
                "tool_calls": summary.get("tool_calls", 0),
                "tool_errors": summary.get("tool_errors", 0),
                "provider_errors": summary.get("provider_errors", 0),
            }
            if error_type is not None:
                ended["error_type"] = error_type
            # Hedged-turn and screen-call stats: counts and timings per route,
            # never conversation text (see session_llm.note_turn, screen._note_call).
            if isinstance(session_llm, SessionLLM):
                for turn in session_llm.turn_stats:
                    analytics.capture(distinct_id, "tutor_llm_turn", {
                        "room": ctx.room.name,
                        "primary": turn.get("primary"),
                        "route": turn.get("winner"),
                        "winner": turn.get("winner"),
                        "ttft_s": turn.get("ttft_s"),
                        "hedged": bool(turn.get("hedged")),
                    })
                ended.update(session_llm.hedge_summary_for_analytics())
            ended.update(screen.screen_stats_summary())
            analytics.capture(distinct_id, "tutor_session_ended", ended)
        finally:
            # Off the event loop with a short timeout: a slow analytics
            # backend must not delay the session teardown.
            await analytics.aclose()
            # The shared loop-owned transports (tutor routes, screen calls)
            # die with this job's loop: close them now so a later loop never
            # reuses a transport bound to a closed one.
            try:
                from .http_clients import aclose_shared_clients

                await aclose_shared_clients()
            except Exception:  # noqa: BLE001 - shutdown hygiene, never fatal
                log.debug("closing shared HTTP clients failed", exc_info=True)
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
    idle_done: asyncio.Event | None = None,
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
    if idle_done is not None:
        waits.append(asyncio.create_task(idle_done.wait()))
    try:
        await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # The losing waiters would stay pending past teardown.
        for waiter in waits:
            if not waiter.done():
                waiter.cancel()
    if provider_failed is not None and provider_failed.is_set() and not left.is_set():
        # The provider refused the turn and will not retry it. Say why without the LLM
        # and end; the 2026-11-06 note in safe_interrupt is the same lesson: a dead
        # provider must not leave the browser sitting in a silent room.
        outcome = "provider_error"
        await say_provider_failed(session, prompt.learner_locale(learner))
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
            await tutor.send_note(get_locale(prompt.learner_locale(tutor.learner)).DEFAULT_NOTE_TOPIC)
    elif idle_done is not None and idle_done.is_set() and not left.is_set():
        # Long learner silence (idle.py): end through the same clean path —
        # one short fixed line instead of the LLM goodbye, the note saved as
        # usual, and the page told why before the room goes away so it shows
        # the normal end card with the idle message, not an error banner.
        outcome = "idle_timeout"
        # Tell the page first: the goodbye and the note take seconds, so the
        # reason is there long before the room delete disconnects it.
        try:
            await ctx.room.local_participant.send_text(
                json.dumps({"type": "ended", "reason": "idle_timeout"}),
                topic="tutor-event")
        except Exception as error:
            log.warning("could not send the idle end reason: %s", error)
        await tutor.set_mode("ending")
        safe_interrupt(session, "ending")
        locale = prompt.learner_locale(tutor.learner)
        notes_before = tutor.notes_saved
        # Like Avsluta: the model saves this session's note and says a short
        # goodbye, bounded in time. If it cannot, the fixed line is spoken.
        said = False
        handle = None
        try:
            debug.record("prompt", {"kind": "idle_goodbye"})
            handle = prompt_event(session, prompt.IDLE_END_INSTRUCTION)
            await asyncio.wait_for(handle.wait_for_playout(), timeout=30)
            # wait_for_playout also returns for a failed or interrupted
            # generation: only a played reply with an assistant message counts.
            said = (not handle.interrupted and handle.exception() is None
                    and any(getattr(item, "role", None) == "assistant"
                            for item in handle.chat_items))
        except Exception as error:
            log.warning("idle goodbye via the model failed: %s", error)
            debug.record("goodbye", {"ok": False, "error": f"{type(error).__name__}"})
        if not said:
            # Stop a slow model reply first so it cannot talk over the fixed
            # line or save a note while the fallback runs.
            if handle is not None and not handle.done():
                try:
                    handle.interrupt(force=True)
                except Exception as error:
                    log.warning("could not stop the idle goodbye reply: %s", error)
            await say_idle_goodbye(session, locale)
        if tutor.notes_saved == notes_before:
            await tutor.send_note(get_locale(locale).DEFAULT_NOTE_TOPIC)
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
