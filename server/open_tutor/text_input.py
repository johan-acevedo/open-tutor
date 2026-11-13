"""The child's typed chat (``lk.chat``) must never vanish.

LiveKit delivers a text stream only to a topic handler that is registered when the
stream arrives; a stream with no handler is disposed and only an INFO line on the
``livekit`` logger (level WARN by default in our worker) says so. RoomIO registers
its ``lk.chat`` handler inside ``AgentSession.start()``, which is after the agent
participant has joined and after ``wait_for_participant``, TTS/STT construction and
the debug log. A child (or the e2e probe) typing in that window lost the message
with no trace at all on 2026-11-12/13: no ``chat_item``, no answer, no error.

RoomIO's default callback has two more ways to lose a message silently: it has no
timeout on the stream read, and ``RoomIO`` catches and logs (but discards) an
exception raised by the callback, so a message handled with an error leaves
nothing in the session trail.

This module owns ``lk.chat`` from the moment the room connects. It records every
message as a session event on arrival, queues messages until the session can
answer, answers a message typed during the greeting with the greeting and the
answer in one reply, and records a failure instead of dropping the turn. Handling
follows the documented behaviour of the framework's default callback: interrupt
the current speech, then generate a reply.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Callable

from livekit import rtc
from livekit.agents import AgentSession

TOPIC_CHAT = "lk.chat"

# A stream that has opened but never completes would otherwise wait forever
# (RoomIO reads it with no timeout) and the child's message would just not exist.
READ_TIMEOUT_S = 15.0

# One reply is enough: the child has not heard the greeting yet, so greet and answer.
GREET_AND_ANSWER = (
    "The child typed this before they heard your greeting. Greet them by name in one "
    "short sentence, then answer what they wrote, in one reply."
)

RecordFn = Callable[[str, dict[str, Any]], None]


class TypedChat:
    """Owns the child's typed messages for one session.

    Lifecycle in the worker: create it right after the room connects and register
    :meth:`on_stream`; attach the session before it starts; call :meth:`start` once
    the session runs. Anything typed before that is queued, not dropped.
    """

    def __init__(self) -> None:
        self._record: RecordFn | None = None
        self._buffered: list[tuple[str, dict[str, Any]]] = []
        self._session: AgentSession | None = None
        self._expected_identity: str | None = None
        self._ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._pending: list[str] = []
        self._heard = False  # the tutor has said (or started saying) something already
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- wiring ----------------------------------------------------------------

    def attach_record(self, record: RecordFn) -> None:
        """Start recording; events raised before the debug log existed are kept."""
        self._record = record
        for event, data in self._buffered:
            record(event, data)
        self._buffered.clear()

    def expect(self, identity: str | None) -> None:
        """Only the linked child's messages are ours to answer."""
        self._expected_identity = identity

    def attach_session(self, session: AgentSession) -> None:
        self._session = session

    def mark_heard(self) -> None:
        """The tutor has started speaking: the greeting no longer needs merging."""
        self._heard = True

    # ---- the room handler ------------------------------------------------------

    def on_stream(self, reader: rtc.TextStreamReader, participant_identity: str) -> None:
        task = asyncio.create_task(self._read(reader, participant_identity))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- session start ---------------------------------------------------------

    async def start(self, greeting: str, prompt: Callable[[str], Any]) -> None:
        """Open the game: greet the child unless a message is already waiting.

        ``prompt`` is the worker's ``prompt_event``: it asks for a reply to a session
        event. A message typed before this point is answered instead, with the
        greeting folded into that reply.
        """
        self._ready.set()
        async with self._lock:
            if not self._pending:
                self._event("prompt", {"kind": "greeting"})
                prompt(greeting)
                return
        await self._flush()

    # ---- internals -------------------------------------------------------------

    async def _read(self, reader: rtc.TextStreamReader, participant_identity: str) -> None:
        if self._expected_identity and participant_identity != self._expected_identity:
            return
        try:
            text = await asyncio.wait_for(reader.read_all(), timeout=READ_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._event("chat_typed_failed", {"stage": "read", "error": "timeout"})
            return
        except Exception as error:  # the reader died: the message exists, its text does not
            self._event("chat_typed_failed", {"stage": "read",
                                              "error": f"{type(error).__name__}: {error}"[:300]})
            return
        text = (text or "").strip()
        if not text:
            self._event("chat_typed_failed", {"stage": "read", "error": "empty"})
            return
        # The durable record of the child's turn: written on arrival, before any of the
        # reply machinery can lose it.
        self._event("chat_typed", {"text": text[:2000], "queued": not self._ready.is_set(),
                                   "greeted": self._heard})
        self._pending.append(text)
        await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._ready.is_set() or self._session is None:
                return
            while self._pending:
                text = "\n".join(self._pending)
                self._pending.clear()
                await self._reply(text)

    async def _reply(self, text: str) -> None:
        session = self._session
        if session is None:
            return
        greet = not self._heard
        try:
            with contextlib.suppress(RuntimeError):
                # Uninterruptible speech or a closed session must not drop the turn;
                # the reply is queued behind the speech in that case.
                await session.interrupt()
            if self._pending:
                # Typed while we waited for the interruption: answer it in this reply.
                text = "\n".join([text, *self._pending])
                self._pending.clear()
            self._event("prompt", {"kind": "typed_chat", "greet": greet, "chars": len(text)})
            session.generate_reply(
                user_input=text,
                **({"instructions": GREET_AND_ANSWER} if greet else {}),
            )
        except Exception as error:
            self._event("chat_typed_failed", {"stage": "reply", "greet": greet,
                                              "error": f"{type(error).__name__}: {error}"[:300]})

    def _event(self, event: str, data: dict[str, Any]) -> None:
        if self._record is None:
            self._buffered.append((event, data))
        else:
            self._record(event, data)
