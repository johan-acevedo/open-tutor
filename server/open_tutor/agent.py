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
from typing import Any, Callable, Literal

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
from .board import (
    DiagramRole,
    HtmlItem,
    Ids,
    MindmapItem,
    Note,
    ResourceItem,
    Step,
    StepsItem,
    SvgItem,
    TextItem,
    youtube_embed,
)
from .diagram import Diagram, DiagramError, LinkSpec, NodeSpec
from .config import AGENT_NAME, env_float
from .tutor_llm import build_llm, warm_up
from .speech import speakable_stream, unspoken_stream

log = logging.getLogger("open-tutor")

BOARD_RPC_TIMEOUT = 6.0
# The first diagram of a session loads the drawing library in the browser; give a slow line time.
DIAGRAM_RPC_TIMEOUT = 12.0
HOMEWORK_SETTLE = 1.2  # seconds to wait for more PDF pages before responding


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
    kwargs: dict[str, Any] = {
        "model": os.environ.get("TUTOR_TTS_MODEL", "eleven_flash_v2_5"),
        "language": "sv",
        "api_key": os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY"),
    }
    if os.environ.get("TUTOR_TTS_VOICE"):
        kwargs["voice_id"] = os.environ["TUTOR_TTS_VOICE"]
    return elevenlabs.TTS(**kwargs)


class Tutor(Agent):
    def __init__(self, learner: dict[str, Any], room: rtc.Room) -> None:
        super().__init__(instructions=prompt.instructions(learner))
        self.learner = learner
        self.room = room
        self.ids = Ids()
        self.diagrams: dict[str, Diagram] = {}
        self._diagram_lock = asyncio.Lock()  # one diagram change at a time, in the order the tools ran
        self.child_identity: str | None = None
        self.mode = "talking"
        self.notes_saved = 0
        self._http: aiohttp.ClientSession | None = None

    # ---- board -----------------------------------------------------------------

    async def _rpc(self, method: str, payload: dict[str, Any], timeout: float = BOARD_RPC_TIMEOUT) -> bool:
        if not self.child_identity:
            return False
        try:
            reply = await self.room.local_participant.perform_rpc(
                destination_identity=self.child_identity,
                method=method,
                payload=json.dumps(payload, ensure_ascii=False),
                response_timeout=timeout,
            )
            ok = bool(json.loads(reply or "{}").get("ok"))
        except Exception as error:  # timeout, child left, or render error
            log.warning("board rpc %s failed: %s", method, error)
            return False
        log.info("board rpc %s %s acknowledged=%s", method, payload.get("id"), ok)
        return ok

    async def _show(self, item) -> str:
        shown = await self._rpc("board.show", item.model_dump(exclude_none=True))
        if not shown:
            return f"The board could not show item {item.id}. Explain in words instead, briefly."
        return f"Item {item.id} is now visible on the board. You can talk about it."

    @function_tool()
    async def show_steps(self, context: RunContext, title: str, steps: list[Step]) -> str:
        """Show a worked equation or process step by step on the board.

        Args:
            title: Short Swedish heading, e.g. "Ekvationer · ett steg i taget".
            steps: Rows in order. `tex` is plain LaTeX without $ (e.g. "3x + 5 = 20"). From the
                second row on, `op` is the operation that turned the PREVIOUS row into THIS row (e.g.
                "-5" or "\\div 3") and `note` says the same in a few Swedish words ("Ta bort 5 på båda
                sidor"). The first row has no op. Titles use ordinary notation, not spoken words.
        """
        try:
            item = StepsItem(id=self.ids.next(), title=title, steps=steps)
        except ValidationError as error:
            return f"Invalid steps: {error.errors()[0]['msg']}"
        result = await self._show(item)
        return result + " Use focus_step with this id to highlight a row (0-based) as you talk about it."

    @function_tool()
    async def focus_step(self, context: RunContext, item_id: str, step: int) -> str:
        """Highlight one row (0-based) of a steps item while you talk about it."""
        ok = await self._rpc("board.focus", {"id": item_id, "step": step})
        return "Highlighted." if ok else "Could not highlight that row."

    @function_tool()
    async def show_text(self, context: RunContext, title: str, markdown: str) -> str:
        """Show a short explanation, key words or a task on the board.

        Args:
            title: Short Swedish heading.
            markdown: A few short lines. Simple Markdown; LaTeX inside $…$ or $$…$$.
        """
        try:
            return await self._show(TextItem(id=self.ids.next(), title=title, markdown=markdown))
        except ValidationError as error:
            return f"Invalid text: {error.errors()[0]['msg']}"

    @function_tool()
    async def show_ideas(self, context: RunContext, center: str, ideas: list[str], title: str = "") -> str:
        """Organise the child's own ideas around a centre, in their words (for writing, essays, book reviews).

        Args:
            center: The subject, e.g. a book title.
            ideas: 1–8 short phrases, quoting what the child said where possible.
            title: Optional heading, e.g. "Dina tankar om boken".
        """
        try:
            item = MindmapItem(id=self.ids.next(), title=title or None, center=center, ideas=ideas)
        except ValidationError as error:
            return f"Invalid ideas: {error.errors()[0]['msg']}"
        return await self._show(item)

    @function_tool()
    async def show_svg(self, context: RunContext, title: str, svg: str) -> str:
        """Draw a diagram as a complete SVG document (viewBox set, no scripts).

        Use the board palette: background transparent, lines #F3F5F8 or #A78BFA, highlights #22D3EE,
        text in Swedish at font-size >= 18.
        """
        try:
            return await self._show(SvgItem(id=self.ids.next(), title=title, svg=svg))
        except ValidationError as error:
            return f"Invalid svg: {error.errors()[0]['msg']}"

    # ---- diagrams ----------------------------------------------------------------------
    # The worker owns each diagram (nodes, links, layout, focus) and sends the whole item with a
    # rising `rev` on every change. The browser acknowledges once the scene shows that revision, so
    # a tool result never reports a drawing the child cannot see, and a missed update is repaired by
    # the next one. Changes run one at a time under a lock.

    async def _diagram_change(self, diagram_id: str, change: Callable[[Diagram], None]) -> str:
        async with self._diagram_lock:
            diagram = self.diagrams.get(diagram_id)
            if diagram is None:
                known = ", ".join(self.diagrams) or "none yet"
                return f"There is no diagram {diagram_id}. Diagrams: {known}. Start one with show_diagram."
            try:
                change(diagram)
            except DiagramError as error:
                return f"Diagram {diagram_id} is unchanged: {error}"
            except ValidationError as error:
                return f"Diagram {diagram_id} is unchanged: {error.errors()[0]['msg']}"
            return await self._diagram_send(diagram)

    async def _diagram_send(self, diagram: Diagram) -> str:
        method = "board.update" if diagram.shown else "board.show"
        payload = diagram.item().model_dump(exclude_none=True)
        diagram.shown = await self._rpc(method, payload, timeout=DIAGRAM_RPC_TIMEOUT)
        if not diagram.shown:
            return (
                f"The board did not confirm diagram {diagram.id} (revision {diagram.rev}); the child may not "
                "see it yet. The diagram is kept and your next diagram call sends all of it again. Explain in "
                "words, briefly."
            )
        return f"Diagram {diagram.id} is now visible (revision {diagram.rev}). {diagram.describe()}"

    @function_tool()
    async def show_diagram(
        self,
        context: RunContext,
        title: str,
        nodes: list[NodeSpec],
        links: list[LinkSpec] | None = None,
        layout: Literal["radial", "flow"] = "radial",
    ) -> str:
        """Start a connected diagram: a mind map or a flow of boxes and arrows (not equations).

        Start small (the main subject and one to three nodes) and grow it with `add_to_diagram` as you
        talk, so the child sees it appear in step with your words. Equations stay in `show_steps`.
        You choose short ids, labels and links; the board does the drawing and layout.

        Args:
            title: Short Swedish heading.
            nodes: Boxes, each with a short id of your choice, a short Swedish label and an optional
                role. The first node of a radial diagram is the centre.
            links: Arrows between node ids, optionally labelled with one or two words.
            layout: "radial" for a mind map around the first node, "flow" for steps left to right
                (a process, a reaction as generic labels, cause and effect).
        """
        async with self._diagram_lock:
            diagram = Diagram(self.ids.next(), title or None, layout or "radial")
            try:
                diagram.add(nodes, links or [])
            except DiagramError as error:
                return f"No diagram was started: {error}"
            except ValidationError as error:
                return f"No diagram was started: {error.errors()[0]['msg']}"
            self.diagrams[diagram.id] = diagram
            return await self._diagram_send(diagram)

    @function_tool()
    async def add_to_diagram(
        self,
        context: RunContext,
        diagram_id: str,
        nodes: list[NodeSpec] | None = None,
        links: list[LinkSpec] | None = None,
    ) -> str:
        """Add nodes and/or links to a diagram. Existing nodes keep their place in a mind map.

        Args:
            diagram_id: The id returned by show_diagram, e.g. "b3".
            nodes: New nodes with new ids.
            links: New arrows between existing or new node ids.
        """
        if not nodes and not links:
            return "Nothing to add: give nodes or links."
        return await self._diagram_change(diagram_id, lambda d: d.add(nodes or [], links or []))

    @function_tool()
    async def edit_diagram(
        self,
        context: RunContext,
        diagram_id: str,
        target_id: str,
        text: str | None = None,
        role: DiagramRole | None = None,
    ) -> str:
        """Change the label or role of one node, or the label of one link, by its id.

        Args:
            diagram_id: The diagram's id.
            target_id: A node id, or a link id like "l2".
            text: The new label. For a link, an empty text removes its label.
            role: New role for a node: center, idea, step, result or note.
        """
        if text is None and role is None:
            return "Nothing to change: give text or role."
        return await self._diagram_change(diagram_id, lambda d: d.edit(target_id, text, role))

    @function_tool()
    async def remove_from_diagram(self, context: RunContext, diagram_id: str, ids: list[str]) -> str:
        """Remove nodes (with their arrows) or single links from a diagram, by id.

        Args:
            diagram_id: The diagram's id.
            ids: Node ids and/or link ids.
        """
        return await self._diagram_change(diagram_id, lambda d: d.remove(ids))

    @function_tool()
    async def focus_diagram(self, context: RunContext, diagram_id: str, ids: list[str] | None = None) -> str:
        """Highlight nodes or links of a diagram while you talk about them, and zoom to them.
        Call it with no ids to clear the highlight and show the whole diagram again.

        Args:
            diagram_id: The diagram's id.
            ids: Node and/or link ids to highlight.
        """
        return await self._diagram_change(diagram_id, lambda d: d.set_focus(ids or []))

    @function_tool()
    async def show_html(self, context: RunContext, title: str, html: str, height: int = 360) -> str:
        """Show an interactive or animated explanation as a self-contained HTML document.

        It runs in an isolated frame with no network except scripts from cdn.jsdelivr.net. Dark
        background #181B22, text #F3F5F8, accents #22D3EE and #A78BFA. Keep it small and clear.

        Args:
            height: Frame height in pixels, 120–900.
        """
        try:
            item = HtmlItem(id=self.ids.next(), title=title, html=html, height=max(120, min(height, 900)))
        except ValidationError as error:
            return f"Invalid html: {error.errors()[0]['msg']}"
        return await self._show(item)

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
        self.mode = mode
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
            clicked: What they understood.
            tricky: What is still hard.
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
            return "Could not save the note."
        self.notes_saved += 1
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

    async def add_homework(self, parts: list[Any], description: str) -> None:
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
        learner = json.loads(child.metadata or "{}").get("learner", {})
    except json.JSONDecodeError:
        learner = {}

    tutor = Tutor(learner, ctx.room)
    tutor.child_identity = child.identity

    session = AgentSession(
        stt=build_stt(),
        llm=build_llm(ctx.room.name),
        tts=build_tts(),
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
        session.interrupt()
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
        image = llm.ImageContent(image=f"data:{mime};base64,{base64.b64encode(bytes(data)).decode()}", inference_detail="high")
        pending.append(([image], description))
        schedule_reply()

    async def on_homework_text(reader: rtc.TextStreamReader, identity: str) -> None:
        text = (await reader.read_all())[:12000]
        attrs = dict(reader.info.attributes or {})
        pending.append(([text], f"pasted text (board id {attrs.get('itemId', '?')})"))
        schedule_reply()

    ending = asyncio.Event()

    async def on_session_event(reader: rtc.TextStreamReader, identity: str) -> None:
        try:
            event = json.loads(await reader.read_all())
        except json.JSONDecodeError:
            return
        if event.get("type") == "end":
            ending.set()
        elif event.get("type") == "resource-closed":
            await tutor.set_mode("talking")
            prompt_event(session, "The child finished the resource. Ask briefly what they noticed or thought.")

    def spawn(coro_fn):
        def handler(reader, identity):
            asyncio.create_task(coro_fn(reader, identity))
        return handler

    ctx.room.register_byte_stream_handler("homework", spawn(on_homework_image))
    ctx.room.register_text_stream_handler("homework-text", spawn(on_homework_text))
    ctx.room.register_text_stream_handler("session-event", spawn(on_session_event))

    await session.start(
        agent=tutor,
        room=ctx.room,
        room_options=room_io.RoomOptions(participant_identity=child.identity),
        # Children's audio and transcripts are not uploaded to LiveKit Cloud observability.
        record=os.environ.get("TUTOR_CLOUD_RECORDING") == "1",
    )
    await ctx.room.local_participant.set_attributes({"tutor.mode": "talking"})
    prompt_event(session, prompt.greeting_instruction(learner))

    left = asyncio.Event()
    ctx.room.on("participant_disconnected", lambda p: p.identity == child.identity and left.set())
    await asyncio.wait(
        [asyncio.create_task(ending.wait()), asyncio.create_task(left.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    if ending.is_set():
        await tutor.set_mode("ending")
        session.interrupt()
        handle = prompt_event(session, prompt.END_INSTRUCTION)
        try:
            await asyncio.wait_for(handle.wait_for_playout(), timeout=30)
        except Exception as error:
            log.warning("goodbye did not finish: %s", error)
        if tutor.notes_saved == 0:
            await tutor.send_note("Läxhjälp")
    if tutor._http:
        await tutor._http.close()
    await session.aclose()
    # Deleting the room disconnects the browser, which then shows its end card.
    try:
        await ctx.delete_room()
    except Exception as error:
        log.warning("could not delete room: %s", error)
    ctx.shutdown("session ended")


if __name__ == "__main__":
    cli.run_app(server)
