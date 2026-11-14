"""One tutor model per session, with the route decided by a warm-up race.

There used to be one provider per session and no backup. On 2026-11-14 a slow
provider made the first LLM call time out three times at 10 s each and the child
waited about 50 s for the greeting. Now the greeting is spoken without the LLM (see
``agent.py``) and, while it plays, a short warm-up request goes to every candidate
route; the faster one serves the whole session.

Two rules shape everything here:

- **The route is fixed per session.** Gemini rejects a retained history that holds
  function calls it did not sign, so switching per turn is unsafe. The only switch
  after the decision is a failover to a route that does not need thought signatures.
- **The child never waits on the race.** If their first turn arrives before the race
  decided, the request waits for the decision, which is bounded by the warm-up cap.

A slow provider can still spike mid-session, after the race. Each turn therefore
starts on the current primary route and, when hedging is enabled and safe, races
an identical request on the other route past a short deadline (see
``tutor_hedge_after_s``). The first stream to yield a chunk wins; nothing is
forwarded before the winner is decided, so the child never hears a mixed reply.
Hedging only runs between routes that both ignore thought signatures, and a
secondary route that wins twice in a row becomes the primary (sticky preference).
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import time
from typing import Any

from livekit.agents import APIConnectOptions, llm
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, NotGivenOr

from .config import LLMRoute
from .debug_log import record_active

log = logging.getLogger("open-tutor")

# A route that has not produced its first token by now loses the race.
WARM_UP_CAP_S = 5.0
# What the warm-up asks for: one word, so the request costs a handful of output tokens
# and is thrown away after the first chunk. The system message is the real tutor prompt,
# so the provider can cache that prefix while the greeting plays.
WARM_UP_PROMPT = "Svara bara med ordet hej."

# Hedged turns: how long the primary route gets the turn to itself before the same
# request also starts on the other route. `TUTOR_LLM_HEDGE_AFTER_S` overrides it;
# 0 or empty disables hedging (today's single-route turns). Parsed per turn, so
# tests and the operator change it without restarting the session object.
DEFAULT_HEDGE_AFTER_S = 2.5

# Loser cleanup never delays the winner, the session or shutdown: a
# discarded side's pump cancel + stream close runs concurrently with winner
# forwarding and is force-cancelled after this long (log once, no text).
LOSER_CLEANUP_BOUND_S = 2.0


def _cancel_count() -> int:
    """How many times the current task was cancelled (0 off-loop)."""
    task = asyncio.current_task()
    try:
        return task.cancelling() if task is not None else 0
    except AttributeError:  # Python < 3.11: no cancelling(); treat as 0/1
        return 0


def tutor_hedge_after_s(environ: dict[str, str] | None = None) -> float | None:
    """Seconds before a slow turn is hedged, or ``None`` when hedging is off.

    Unset means the default; empty or ``0`` means off (today's single-route
    turns); anything unparseable falls back to the default."""
    if environ is None:
        raw = os.environ.get("TUTOR_LLM_HEDGE_AFTER_S")
    else:
        raw = environ.get("TUTOR_LLM_HEDGE_AFTER_S")
    if raw is None:
        return DEFAULT_HEDGE_AFTER_S
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_HEDGE_AFTER_S
    return None if value <= 0 else value

PREFERRED, FALLBACK = "preferred", "fallback"


def choose_route(
    preferred_ttft: float | None,
    fallback_ttft: float | None,
    prefer_within: float,
    *,
    has_fallback: bool = True,
) -> str:
    """Which candidate serves the session, from the two measured warm-up times.

    ``None`` means the route errored or had not answered within the cap (it loses).
    - The preferred route wins if it answered within ``prefer_within`` or was the
      faster of the two.
    - Otherwise the other route wins, if it answered at all.
    - If neither answered, the preferred route stays and normal error handling applies.
    """
    if not has_fallback:
        return PREFERRED
    if preferred_ttft is None and fallback_ttft is None:
        return PREFERRED
    if preferred_ttft is None:
        return FALLBACK
    if fallback_ttft is None:
        return PREFERRED
    if preferred_ttft <= prefer_within:
        return PREFERRED
    return PREFERRED if preferred_ttft <= fallback_ttft else FALLBACK


def choice_reason(
    preferred_ttft: float | None,
    fallback_ttft: float | None,
    prefer_within: float,
    chosen: str,
    *,
    has_fallback: bool = True,
    not_awaited: frozenset[str] | set[str] | None = None,
) -> str:
    """A short, log-safe explanation of the choice (never contains speech).

    ``not_awaited`` names the routes whose warm-up was cancelled early because
    the preferred route was already fast enough. That is not a failure: saying
    "only the preferred route answered" would read as if the backup was down.
    """
    if not has_fallback:
        return "single route"
    if preferred_ttft is None and fallback_ttft is None:
        return "neither route answered; keeping the preferred one"
    if chosen == PREFERRED:
        if preferred_ttft is None:  # unreachable, kept for clarity
            return "preferred route"
        if fallback_ttft is None:
            if not_awaited and "fallback" in not_awaited:
                return (
                    f"preferred route answered within {prefer_within:g} s; "
                    "other route not awaited"
                )
            return "only the preferred route answered"
        if preferred_ttft <= prefer_within:
            return f"preferred route answered within {prefer_within:g} s"
        return "preferred route was the faster one"
    if preferred_ttft is None:
        return "preferred route did not answer"
    return "the other route was faster"


class SessionLLM(llm.LLM):
    """A thin ``llm.LLM`` that delegates ``chat()`` to the route chosen once per session.

    ``AgentSession`` takes its LLM at construction and exposes no setter, and an
    ``Agent.update_options(llm=...)`` swap only applies to the next turn, so a
    delegating wrapper is the clean way to keep one decision for the whole session.
    The official ``FallbackAdapter`` is per-request failover, which is exactly the
    per-turn switching Gemini's thought signatures forbid.
    """

    def __init__(
        self,
        preferred: llm.LLM,
        preferred_route: LLMRoute,
        fallback: llm.LLM | None = None,
        fallback_route: LLMRoute | None = None,
        *,
        prefer_within: float = 1.5,
        warm_up_cap: float = WARM_UP_CAP_S,
    ) -> None:
        super().__init__()
        if (fallback is None) != (fallback_route is None):
            raise ValueError("a fallback needs both its model and its route")
        self._preferred = preferred
        self._preferred_route = preferred_route
        self._fallback = fallback
        self._fallback_route = fallback_route
        self._current = preferred
        self._prefer_within = prefer_within
        self._warm_up_cap = warm_up_cap
        # No fallback configured: today's single-route behaviour, nothing to race.
        self._decided = fallback is None
        self._decision = asyncio.Event()
        if self._decided:
            self._decision.set()
        self._timings: dict[str, float | None] = {}
        # Routes whose warm-up never finished because the preferred route was
        # already fast enough (cancelled, not failed; see warm_up).
        self._not_awaited: set[str] = set()
        self._choice: str = PREFERRED
        self._reason = "single route" if fallback is None else "not decided yet"
        # Hedged-turn stats for the debug trail and analytics (see note_turn).
        self._turn_stats: list[dict[str, Any]] = []
        self._hedge_streak = 0  # consecutive turns the secondary route won
        self._sticky_switches = 0

    # ---- what the session and its metrics see -----------------------------------

    @property
    def route_name(self) -> str:
        return self._fallback_route.name if self._current is self._fallback else self._preferred_route.name

    @property
    def chosen_route(self) -> LLMRoute:
        return self._fallback_route if self._current is self._fallback else self._preferred_route

    @property
    def model(self) -> str:
        return self._current.model

    @property
    def provider(self) -> str:
        return self._current.provider

    def _prewarm_impl(self) -> None:
        self._preferred.prewarm()
        if self._fallback is not None:
            self._fallback.prewarm()

    async def aclose(self) -> None:
        candidates = [self._preferred] if self._fallback is None else [self._preferred, self._fallback]
        for inner in candidates:
            await inner.aclose()
        await super().aclose()

    # ---- the race ----------------------------------------------------------------

    async def warm_up(self, *, instructions: str, tools: list[llm.Tool] | None = None) -> dict[str, Any]:
        """Measure both candidates, then fix the session's route. Safe to await twice."""
        if self._decided:
            return self.result()
        if self._fallback is None or self._fallback_route is None:
            self._decide(self._preferred, PREFERRED, "single route")
            return self.result()
        named = {
            self._preferred_route.name: self._preferred,
            self._fallback_route.name: self._fallback,
        }
        tasks = {
            name: asyncio.create_task(
                self._first_token_s(model, instructions, tools), name=f"warm-up-{name}"
            )
            for name, model in named.items()
        }
        try:
            pending = dict(tasks)
            while pending:
                await asyncio.wait(set(pending.values()), return_when=asyncio.FIRST_COMPLETED)
                for name, task in list(pending.items()):
                    if task.done():
                        self._timings[name] = task.result()  # _first_token_s never raises
                        del pending[name]
                if not pending:
                    break
                preferred_s = self._timings.get(self._preferred_route.name)
                # A preferred route that is fast enough ends the race at once; no need
                # to wait for the other route's answer. The other warm-up is
                # cancelled, not failed, and recorded as not awaited.
                if preferred_s is not None and preferred_s <= self._prefer_within:
                    for name in pending:
                        self._not_awaited.add(
                            "fallback" if name == self._fallback_route.name else name
                        )
                    break
            preferred_ttft = self._timings.get(self._preferred_route.name)
            fallback_ttft = self._timings.get(self._fallback_route.name)
            choice = choose_route(preferred_ttft, fallback_ttft, self._prefer_within)
            reason = choice_reason(preferred_ttft, fallback_ttft, self._prefer_within,
                                   choice, not_awaited=self._not_awaited)
            self._decide(
                self._fallback if choice == FALLBACK else self._preferred, choice, reason
            )
        except asyncio.CancelledError:
            self._decide(self._preferred, PREFERRED, "warm-up cancelled; keeping the preferred route")
            raise
        finally:
            for task in tasks.values():
                if not task.done():
                    task.cancel()
            if not self._decided:  # a crash must never leave a request waiting
                self._decide(self._preferred, PREFERRED, "warm-up did not finish")
        return self.result()

    async def _first_token_s(
        self, model: llm.LLM, instructions: str, tools: list[llm.Tool] | None
    ) -> float | None:
        """Seconds to the warm-up's first token; ``None`` when the route lost."""
        try:
            return await asyncio.wait_for(
                self._measure(model, instructions, tools), timeout=self._warm_up_cap
            )
        except asyncio.TimeoutError:
            return None
        except asyncio.CancelledError:
            raise
        except Exception as error:  # a provider error simply loses the race
            log.warning("warm-up route %s failed: %s", model.label, error)
            return None

    async def _measure(
        self, model: llm.LLM, instructions: str, tools: list[llm.Tool] | None
    ) -> float | None:
        ctx = llm.ChatContext()
        ctx.add_message(role="system", content=instructions)
        ctx.add_message(role="user", content=WARM_UP_PROMPT)
        conn_options = APIConnectOptions(max_retry=0, timeout=self._warm_up_cap)
        started = time.perf_counter()
        stream = model.chat(chat_ctx=ctx, tools=tools or [], conn_options=conn_options)
        try:
            async for chunk in stream:
                if chunk.has_response():
                    return time.perf_counter() - started
            return None  # the stream ended without a token
        finally:
            try:
                await stream.aclose()  # the rest of the warm-up answer is not wanted
            except (Exception, asyncio.CancelledError):
                pass

    def _decide(self, model: llm.LLM, choice: str, reason: str) -> None:
        if self._decided:
            return
        self._current = model
        self._choice = choice
        self._reason = reason
        self._decided = True
        self._decision.set()
        self._record_choice()

    def _describe_warm_up(self, name: str | None, ttft: float | None) -> str:
        if name is None:
            return "-"
        if ttft is not None:
            return f"{ttft:.2f} s"
        short = "fallback" if self._fallback_route is not None and name == self._fallback_route.name else name
        if short in self._not_awaited:
            return "not awaited"
        return "did not answer"

    def _record_choice(self) -> None:
        preferred = self._timings.get(self._preferred_route.name)
        fallback = self._timings.get(self._fallback_route.name)
        fallback_name = self._fallback_route.name if self._fallback_route else None
        record_active(
            "llm_chosen",
            {
                "route": self.chosen_route.name,
                "model": self._current.model,
                "choice": self._choice,
                "reason": self._reason,
                "preferred": self._preferred_route.name,
                "fallback": fallback_name,
                "preferred_s": None if preferred is None else round(preferred, 3),
                "fallback_s": None if fallback is None else round(fallback, 3),
                "fallback_not_awaited": bool(
                    fallback_name and (fallback_name in self._not_awaited or "fallback" in self._not_awaited)
                ),
                "prefer_within_s": self._prefer_within,
                "warm_up_cap_s": self._warm_up_cap,
            },
        )
        log.info(
            "tutor LLM chosen %s (%s); warm-up preferred %s %s, fallback %s %s",
            self.chosen_route.name,
            self._reason,
            self._preferred_route.name,
            self._describe_warm_up(self._preferred_route.name, preferred),
            fallback_name if fallback_name else "-",
            self._describe_warm_up(fallback_name, fallback),
        )

    def result(self) -> dict[str, Any]:
        preferred = self._timings.get(self._preferred_route.name)
        fallback = (
            self._timings.get(self._fallback_route.name)
            if self._fallback_route is not None
            else None
        )
        return {
            "route": self.chosen_route.name,
            "model": self._current.model,
            "choice": self._choice,
            "reason": self._reason,
            "preferred_s": None if preferred is None else round(preferred, 3),
            "fallback_s": None if fallback is None else round(fallback, 3),
            "not_awaited": sorted(self._not_awaited),
            "decided": self._decided,
        }

    async def pick(self) -> llm.LLM:
        """The route for this request; waits for the race only if it is still running."""
        if not self._decided:
            try:
                await asyncio.wait_for(self._decision.wait(), timeout=self._warm_up_cap + 1.0)
            except asyncio.TimeoutError:
                self._decide(self._preferred, PREFERRED, "warm-up did not report; keeping the preferred route")
        return self._current

    # ---- failover ----------------------------------------------------------------

    def _other(self, current: llm.LLM) -> llm.LLM | None:
        if self._fallback is None or self._fallback_route is None:
            return None
        return self._fallback if current is self._preferred else self._preferred

    def failover(self, current: llm.LLM, error: BaseException) -> llm.LLM | None:
        """Move the rest of the session to the other candidate, when that is safe.

        Safe means the target does not enforce thought signatures: replaying a
        history that holds another provider's signed calls is fine for a route that
        does not check them, and a request to a route that does would be rejected.
        """
        other = self._other(current)
        if other is None:
            return None
        target_route = self._fallback_route if other is self._fallback else self._preferred_route
        source_route = self._fallback_route if other is self._preferred else self._preferred_route
        if target_route.thought_signatures:
            record_active(
                "llm_failover_skipped",
                {
                    "from": source_route.name,
                    "to": target_route.name,
                    "error": type(error).__name__,
                    "why": "the other route needs thought signatures",
                },
            )
            log.warning("not failing over to %s: it needs thought signatures", target_route.name)
            return None
        self._current = other
        self._reason = f"failed over from {source_route.name}"
        record_active(
            "llm_failover",
            {
                "from": source_route.name,
                "to": target_route.name,
                "model": other.model,
                "error": type(error).__name__,
                "message": str(error)[:300],
            },
        )
        log.warning("tutor LLM failing over to %s for the rest of the session", target_route.name)
        return other

    # ---- hedged turns ------------------------------------------------------------

    def _name_of(self, model: llm.LLM) -> str:
        """Which candidate route an LLM instance is (never message text)."""
        if model is self._fallback:
            return self._fallback_route.name if self._fallback_route else "fallback"
        return self._preferred_route.name

    def hedge_target(self, current: llm.LLM) -> llm.LLM | None:
        """The other route for a hedged turn, or ``None`` to run unhedged.

        Hedging only starts between routes that are safe to swap mid-conversation:
        both must ignore thought signatures (never Gemini). With one route, with
        hedging off, or with a signature-checking route, today's behaviour applies.
        """
        if self._fallback is None or self._fallback_route is None:
            return None
        if tutor_hedge_after_s() is None:
            return None
        current_route = self._fallback_route if current is self._fallback else self._preferred_route
        other_route = self._preferred_route if current is self._fallback else self._fallback_route
        if current_route.thought_signatures or other_route.thought_signatures:
            return None
        return self._other(current)

    def note_turn(
        self,
        *,
        primary: str,
        winner: str | None,
        hedged: bool,
        ttft_s: float | None,
        loser: str,
        primary_ttft_s: float | None = None,
        error: str | None = None,
        failover: bool = False,
    ) -> None:
        """Record one served turn for the debug trail and the analytics summary.

        ``loser`` is ``cancelled``/``error``/``none``; ``primary_ttft_s`` is the
        primary's own first-chunk time when the secondary won but the primary
        answered before it was cancelled (when observed). Only route names,
        timings and error classes: never message text.
        """
        entry: dict[str, Any] = {
            "primary": primary,
            "winner": winner,
            "hedged": hedged,
            "ttft_s": None if ttft_s is None else round(ttft_s, 3),
            "loser": loser,
        }
        if primary_ttft_s is not None:
            entry["primary_ttft_s"] = round(primary_ttft_s, 3)
        if error is not None:
            entry["error"] = error
        self._turn_stats.append(entry)
        record_active("llm_turn", entry)
        if error is None and not failover and winner is not None and winner != primary:
            self._hedge_streak += 1
            if self._hedge_streak >= 2:
                self._switch_primary(winner)
        else:
            self._hedge_streak = 0

    def _switch_primary(self, winner: str) -> None:
        """The secondary route won twice running: it serves the following turns."""
        from_name = self._name_of(self._current)
        if winner == from_name:
            self._hedge_streak = 0
            return
        self._current = self._fallback if self._current is self._preferred else self._preferred
        self._hedge_streak = 0
        self._sticky_switches += 1
        self._reason = f"sticky switch to {winner} after 2 faster turns"
        record_active("llm_sticky_switch", {"from": from_name, "to": winner})
        log.info("tutor LLM sticky switch to %s for the following turns", winner)

    @property
    def turn_stats(self) -> list[dict[str, Any]]:
        """One record per served turn (route names and timings only)."""
        return list(self._turn_stats)

    def hedge_summary_for_analytics(self) -> dict[str, Any]:
        """Per-session hedge stats for ``tutor_session_ended`` (counts and
        timings only; never text)."""
        from .analytics import summarize_llm_turns

        summary = summarize_llm_turns(self._turn_stats)
        return {
            "llm_turns_total": summary["turns_total"],
            "llm_hedged_turns": summary["hedged_turns"],
            "llm_turns_errored": summary["turns_errored"],
            "llm_sticky_switches": self._sticky_switches,
            "llm_routes": summary["routes"],
        }

    # ---- chat --------------------------------------------------------------------

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        return _RoutedStream(
            self,
            chat_ctx=chat_ctx,
            tools=tools or [],
            conn_options=conn_options,
            call_kwargs={
                "parallel_tool_calls": parallel_tool_calls,
                "tool_choice": tool_choice,
                "extra_kwargs": extra_kwargs,
            },
        )


class _TurnEnd:
    """Sentinel: a pumped provider stream ended without further chunks."""

    __slots__ = ()


_TURN_END = _TurnEnd()


class _TurnError:
    """Sentinel: a pumped provider stream failed before finishing."""

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error


async def _pump_stream(stream: llm.LLMStream, tag: str, queue: "asyncio.Queue[tuple[str, Any]]") -> None:
    """Forward one provider stream into the shared race queue until it ends.

    The pump is never cancelled while its stream is still needed: cancelling a
    pending ``LLMStream.__anext__`` would kill that stream's tee leg for later
    reads. Only a discarded (loser, or turn torn down) stream's pump is cancelled,
    and its stream is closed right after.
    """
    try:
        async for chunk in stream:
            queue.put_nowait((tag, chunk))
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 - the race decides from the other side
        queue.put_nowait((tag, _TurnError(error)))
    else:
        queue.put_nowait((tag, _TURN_END))


class _RoutedStream(llm.LLMStream):
    """Forwards one request to the chosen route, with one failover attempt.

    The wrapper itself never retries (``max_retry=0``): each route's own stream owns
    its single retry on that route, and the only extra attempt is the failover to the
    other candidate. A request that already delivered text or a tool call is not
    retried elsewhere, because the child has heard it.

    When hedging is enabled and safe (see ``SessionLLM.hedge_target``), the turn
    starts on the primary route and the same request starts on the other route if
    the primary produced no first chunk within the hedge deadline. The first
    stream to yield a chunk wins; nothing is forwarded before the winner is
    decided, so the child never hears a mixed reply.
    """

    def __init__(
        self,
        owner: SessionLLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
        call_kwargs: dict[str, Any],
    ) -> None:
        self._owner = owner
        self._route_conn_options = conn_options
        self._call_kwargs = call_kwargs
        self._answered = False
        self._ttft: float | None = None
        # Owned loser-cleanup tasks: discarded sides are detached into
        # background tasks (see _spawn_loser_cleanup) so a hanging
        # cancel/aclose never delays winner forwarding. Reaped in the turn's
        # finally and in aclose(), always within LOSER_CLEANUP_BOUND_S.
        self._loser_cleanups: list[asyncio.Task[None]] = []
        super().__init__(
            owner,
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=dataclasses.replace(conn_options, max_retry=0),
        )

    async def _run(self) -> None:
        target = await self._owner.pick()
        other = self._owner.hedge_target(target)
        if other is None:
            await self._forward_with_failover(target)
            return
        await self._forward_hedged(target, other)

    async def _forward_with_failover(self, target: llm.LLM) -> None:
        """Today's behaviour: one route, failing over once when safe."""
        owner = self._owner
        primary_name = owner._name_of(target)
        try:
            ttft = await self._forward(target, self._route_conn_options)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._answered:
                # Something already reached the child; a second route would repeat it.
                record_active(
                    "llm_failed_after_output",
                    {"route": owner.route_name, "error": type(error).__name__,
                     "message": str(error)[:300]},
                )
                owner.note_turn(primary=primary_name, winner=primary_name, hedged=False,
                                 ttft_s=self._ttft, loser="none", error=type(error).__name__)
                raise
            replacement = owner.failover(target, error)
            if replacement is None:
                owner.note_turn(primary=primary_name, winner=None, hedged=False,
                                 ttft_s=None, loser="error", error=type(error).__name__)
                raise
            try:
                ttft = await self._forward(
                    replacement, dataclasses.replace(self._route_conn_options, max_retry=0)
                )
            except Exception as second_error:
                owner.note_turn(primary=primary_name, winner=None, hedged=False,
                                 ttft_s=None, loser="error", error=type(second_error).__name__,
                                 failover=True)
                raise
            owner.note_turn(primary=primary_name, winner=owner._name_of(replacement),
                             hedged=False, ttft_s=ttft, loser="error", failover=True)
            return
        owner.note_turn(primary=primary_name, winner=primary_name, hedged=False,
                         ttft_s=ttft, loser="none")

    async def _forward(self, target: llm.LLM, conn_options: APIConnectOptions) -> float | None:
        """Stream one route to the child; returns seconds to its first chunk."""
        started = time.perf_counter()
        inner = target.chat(
            chat_ctx=self._chat_ctx,
            tools=self._tools,
            conn_options=conn_options,
            **self._call_kwargs,
        )
        try:
            async for chunk in inner:
                if chunk.has_response():
                    if self._ttft is None:
                        self._ttft = time.perf_counter() - started
                    self._answered = True
                await self._event_ch.send(chunk)
        finally:
            try:
                await inner.aclose()
            except (Exception, asyncio.CancelledError):
                pass
        return self._ttft

    async def _forward_hedged(self, primary_llm: llm.LLM, secondary_llm: llm.LLM) -> None:
        """Race the same request on both routes; first chunk wins.

        The primary runs alone until the hedge deadline. Past it, the secondary
        joins and the first stream to yield a (text or tool call) chunk serves the
        whole turn. Attempts stay within today's worst case: the primary keeps its
        one same-route retry, the secondary gets none, and a turn both routes fail
        raises instead of retrying (both were already tried).
        """
        owner = self._owner
        primary_name = owner._name_of(primary_llm)
        secondary_name = owner._name_of(secondary_llm)
        names = {"primary": primary_name, "secondary": secondary_name}
        hedge_after = tutor_hedge_after_s() or DEFAULT_HEDGE_AFTER_S
        started = time.perf_counter()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        streams = {
            "primary": primary_llm.chat(
                chat_ctx=self._chat_ctx, tools=self._tools,
                conn_options=self._route_conn_options, **self._call_kwargs),
        }
        pumps = {
            "primary": asyncio.create_task(
                _pump_stream(streams["primary"], "primary", queue), name="tutor-hedge-primary"),
        }
        secondary_started = False
        buffered: dict[str, list[Any]] = {"primary": [], "secondary": []}
        first_s: dict[str, float] = {}
        errors: dict[str, BaseException] = {}
        ended: set[str] = set()
        winner: str | None = None
        deciding: Any = None
        try:
            while winner is None:
                if not secondary_started:
                    remaining = hedge_after - (time.perf_counter() - started)
                    if remaining <= 0:
                        self._start_secondary(secondary_llm, streams, pumps, queue)
                        secondary_started = True
                        continue
                    try:
                        tag, item = await asyncio.wait_for(queue.get(), timeout=remaining)
                    except TimeoutError:
                        self._start_secondary(secondary_llm, streams, pumps, queue)
                        secondary_started = True
                        continue
                else:
                    tag, item = await queue.get()
                if isinstance(item, _TurnError):
                    errors[tag] = item.error
                    if tag == "primary" and not secondary_started:
                        # The primary is already dead; no point waiting out the deadline.
                        self._start_secondary(secondary_llm, streams, pumps, queue)
                        secondary_started = True
                    elif set(errors) | ended == {"primary", "secondary"}:
                        break  # both sides dead with no winner: today's error path
                    continue
                if item is _TURN_END:
                    ended.add(tag)
                    if set(errors) | ended == {"primary", "secondary"}:
                        break  # both sides done with no winner
                    continue
                if item.has_response() and tag not in first_s:
                    first_s[tag] = time.perf_counter() - started
                if item.has_response():
                    winner, deciding = tag, item
                else:
                    buffered[tag].append(item)
            if winner is None:
                # Both streams ended or failed before any chunk: deliver nothing.
                # A failure raises the primary's error (today's error path); an
                # empty pair of streams ends the turn quietly, as a single empty
                # stream would.
                for chunk in buffered["primary"]:
                    await self._event_ch.send(chunk)
                if errors:
                    # One side failed, the other ended empty: surface the side
                    # that actually errored. (``errors.get("primary",
                    # ``errors["secondary"])`` would evaluate the default
                    # eagerly and raise ``KeyError`` when only the primary
                    # failed.)
                    error = errors["primary"] if "primary" in errors else errors["secondary"]
                    owner.note_turn(primary=primary_name, winner=None, hedged=secondary_started,
                                     ttft_s=None, loser="error", error=type(error).__name__)
                    raise error
                owner.note_turn(primary=primary_name, winner=primary_name,
                                 hedged=secondary_started, ttft_s=None, loser="none")
                return
            loser = "secondary" if winner == "primary" else "primary"
            for chunk in buffered[winner]:
                await self._event_ch.send(chunk)
            await self._event_ch.send(deciding)
            self._answered = True
            # The loser is detached into an owned background cleanup running
            # concurrently with winner forwarding: a hanging cancel/aclose
            # never delays the winner's remaining chunks. Its first-chunk
            # time still counts when it arrived before the detach (harvested
            # below from already-drained stragglers). A caller cancellation
            # landing here aborts the turn at the next await, after the
            # background cleanup is reaped within the bound in the finally.
            entry_cancels = _cancel_count()
            self._spawn_loser_cleanup(loser, pumps, streams, names[loser])
            if _cancel_count() > entry_cancels:
                raise asyncio.CancelledError()
            stragglers = self._drain_queue(queue)
            winner_done = False
            hedged = secondary_started
            if loser == "secondary" and not secondary_started:
                loser_state = "none"  # the secondary never started
            else:
                loser_state = "error" if loser in errors else "cancelled"
            # The turn is recorded only once the winner has served it to the
            # end: a winner that dies mid-answer counts as a failure, never a
            # win, so a partial-then-failed secondary is never promoted and a
            # cancelled turn resets the streak instead of keeping it.
            turn_error: str | None = None
            try:
                for stag, sitem in stragglers:
                    if stag != winner or isinstance(sitem, (_TurnError, _TurnEnd)):
                        if stag != winner and not isinstance(sitem, (_TurnError, _TurnEnd)):
                            # A late loser chunk: never forwarded, but its
                            # first-chunk time counts when it arrived before
                            # the cancel.
                            if sitem.has_response() and stag not in first_s:
                                first_s[stag] = time.perf_counter() - started
                        if stag == winner and isinstance(sitem, _TurnError):
                            # The winner died between the decision and the cancel.
                            record_active(
                                "llm_failed_after_output",
                                {"route": names[winner], "error": type(sitem.error).__name__,
                                 "message": str(sitem.error)[:300]},
                            )
                            raise sitem.error
                        if stag == winner:
                            winner_done = True  # its end marker was already drained
                        continue  # a late loser straggler: never forwarded
                    await self._event_ch.send(sitem)
                if not winner_done:
                    # The winner serves the rest of the turn on its own.
                    while True:
                        tag, item = await queue.get()
                        if tag != winner or isinstance(item, (_TurnError, _TurnEnd)):
                            if isinstance(item, _TurnError):
                                record_active(
                                    "llm_failed_after_output",
                                    {"route": names[winner], "error": type(item.error).__name__,
                                     "message": str(item.error)[:300]},
                                )
                                raise item.error
                            if tag == winner:
                                break  # the winner's stream ended
                            continue  # a late loser straggler: never forwarded
                        await self._event_ch.send(item)
            except asyncio.CancelledError:
                turn_error = "CancelledError"
                raise
            except BaseException as error:  # noqa: BLE001 - recorded below, then raised
                turn_error = type(error).__name__
                raise
            finally:
                owner.note_turn(
                    primary=primary_name, winner=names[winner], hedged=hedged,
                    ttft_s=first_s.get(winner), loser=loser_state,
                    primary_ttft_s=first_s.get("primary") if winner == "secondary" else None,
                    error=turn_error,
                )
        except asyncio.CancelledError:
            owner._hedge_streak = 0  # an unserved race promotes nothing
            raise
        finally:
            await self._close_owned(pumps, streams)

    def _start_secondary(
        self,
        secondary_llm: llm.LLM,
        streams: dict[str, llm.LLMStream],
        pumps: dict[str, asyncio.Task[None]],
        queue: "asyncio.Queue[tuple[str, Any]]",
    ) -> None:
        """Start the identical request on the other route (deadline passed)."""
        streams["secondary"] = secondary_llm.chat(
            chat_ctx=self._chat_ctx, tools=self._tools,
            conn_options=dataclasses.replace(self._route_conn_options, max_retry=0),
            **self._call_kwargs,
        )
        pumps["secondary"] = asyncio.create_task(
            _pump_stream(streams["secondary"], "secondary", queue), name="tutor-hedge-secondary")

    @staticmethod
    def _drain_queue(queue: "asyncio.Queue[tuple[str, Any]]") -> list[tuple[str, Any]]:
        items = []
        while True:
            try:
                items.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                return items

    async def aclose(self) -> None:
        """Close the wrapper and reap owned loser cleanups within the bound."""
        try:
            await super().aclose()
        finally:
            # The turn's finally already reaps in the normal path; this covers
            # a background loser cleanup still in flight after _run finished.
            try:
                await self._reap_loser_cleanups(bound=LOSER_CLEANUP_BOUND_S)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

    def _spawn_loser_cleanup(
        self,
        side: str,
        pumps: dict[str, asyncio.Task[None]],
        streams: dict[str, llm.LLMStream],
        route_name: str,
    ) -> asyncio.Task[None] | None:
        """Detach a discarded side into an owned background cleanup task.

        The pump/stream are popped at once so the turn's ``finally`` never
        double-closes them; the background task cancels the pump and closes
        the stream within ``LOSER_CLEANUP_BOUND_S`` (log once, no text),
        running concurrently with winner forwarding. Owned in
        ``self._loser_cleanups`` and reaped in the turn's finally and in
        ``aclose()``, always within the same bound.
        """
        pump = pumps.pop(side, None)
        stream = streams.pop(side, None)
        if pump is None and stream is None:
            return None

        async def _cleanup() -> None:
            me = asyncio.current_task()
            try:
                bg_before = me.cancelling() if me is not None else 0
            except AttributeError:  # pragma: no cover - Python < 3.11
                bg_before = 0
            try:
                if pump is not None and not pump.done():
                    pump.cancel()
                if pump is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(pump),
                                             timeout=LOSER_CLEANUP_BOUND_S)
                    except TimeoutError:
                        log.warning("tutor hedged-turn loser cleanup timed out; "
                                    "dropping it")
                        pump.cancel()
                        try:
                            await pump
                        except BaseException:  # noqa: BLE001 - dropped, already logged
                            pass
                    except asyncio.CancelledError:
                        # The pump's own cancellation (from the cancel above)
                        # is expected: swallow it. Only propagate when this
                        # background task itself was cancelled (reaping).
                        try:
                            bg_after = me.cancelling() if me is not None else 0
                        except AttributeError:  # pragma: no cover - Python < 3.11
                            bg_after = bg_before
                        if bg_after > bg_before:
                            pump.cancel()
                            try:
                                await pump
                            except BaseException:  # noqa: BLE001 - reaping, propagate
                                pass
                            raise
                        # Expected pump cancel: fall through to stream close.
                        pass
                    except Exception:  # noqa: BLE001 - loser outcome is swallowed
                        pass
                    finally:
                        try:
                            if not pump.cancelled():
                                pump.exception()
                        except BaseException:  # noqa: BLE001 - retrieved, never lost
                            pass
                if stream is not None:
                    try:
                        await asyncio.wait_for(stream.aclose(),
                                             timeout=LOSER_CLEANUP_BOUND_S)
                    except TimeoutError:
                        log.warning("tutor hedged-turn loser cleanup timed out; "
                                    "dropping it")
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 - loser outcome is swallowed
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - cleanup never fails the turn
                pass

        task = asyncio.create_task(_cleanup(), name=f"tutor-hedge-losercleanup-{side}")

        def _retrieve(t: asyncio.Task[None]) -> None:
            try:
                t.exception()
            except BaseException:  # noqa: BLE001 - retrieved, never lost
                pass

        task.add_done_callback(_retrieve)
        self._loser_cleanups.append(task)
        return task

    async def _reap_loser_cleanups(self, bound: float = LOSER_CLEANUP_BOUND_S) -> bool:
        """Wait for owned loser cleanups within ``bound`` (shielded).

        A caller cancellation landing mid-reap does not abort the wait: the
        shield keeps it alive up to the bound, then background tasks are
        force-cancelled and reaped. Returns True when a caller cancellation
        was observed, so the caller re-raises it after everything owned is
        closed. Never waits longer than ``bound`` in total.
        """
        tasks = list(self._loser_cleanups)
        self._loser_cleanups.clear()
        if not tasks:
            return False
        current = asyncio.current_task()
        before = current.cancelling() if current is not None else 0
        deadline = time.monotonic() + max(0.0, bound)
        for task in tasks:
            while not task.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warning("tutor hedged-turn loser cleanup timed out; dropping it")
                    task.cancel()
                    try:
                        await task
                    except BaseException:  # noqa: BLE001 - dropped, already logged
                        pass
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
                except TimeoutError:
                    log.warning("tutor hedged-turn loser cleanup timed out; dropping it")
                    task.cancel()
                    try:
                        await task
                    except BaseException:  # noqa: BLE001 - dropped, already logged
                        pass
                    break
                except asyncio.CancelledError:
                    if current is None or current.cancelling() <= before:
                        break  # the cleanup itself ended cancelled
                    continue  # our caller wants out; the reap still finishes
                except Exception:  # noqa: BLE001 - already retrieved via callback
                    break
            try:
                if not task.cancelled():
                    task.exception()
            except BaseException:  # noqa: BLE001 - retrieved, never lost
                pass
        after = current.cancelling() if current is not None else 0
        return after > before

    async def _close_owned(
        self,
        pumps: dict[str, asyncio.Task[None]],
        streams: dict[str, llm.LLMStream],
        bound: float = LOSER_CLEANUP_BOUND_S,
    ) -> None:
        """Reap background loser cleanups and close remaining sides in ``bound``.

        One overall deadline covers both: a caller cancellation never waits
        longer than ``bound`` in total, then propagates after everything
        owned is closed or force-cancelled.
        """
        current = asyncio.current_task()
        before = current.cancelling() if current is not None else 0
        deadline = time.monotonic() + max(0.0, bound)
        remaining = deadline - time.monotonic()
        if await self._reap_loser_cleanups(bound=max(0.0, remaining)):
            pass  # caller cancel observed; still close the rest within the bound
        remaining = deadline - time.monotonic()
        if await _RoutedStream._stop_all(pumps, streams, bound=max(0.0, remaining)):
            pass
        after = current.cancelling() if current is not None else 0
        if after > before:
            raise asyncio.CancelledError()

    @staticmethod
    async def _shielded_close(awaitable, bound: float = LOSER_CLEANUP_BOUND_S) -> bool:
        """Await ``awaitable`` to completion, swallowing its own outcome.

        A caller cancellation landing mid-close does not abort the close: the
        shield keeps it alive up to ``bound`` seconds, then the awaited side
        is force-cancelled and reaped (log once, no text). Returns True when
        such a cancellation was observed, so the caller re-raises it after
        everything it owns is closed (distinguished from the awaited side's
        own outcome via the task's cancel count). Never waits longer than
        ``bound``.
        """
        current = asyncio.current_task()
        before = current.cancelling() if current is not None else 0
        inner = asyncio.ensure_future(awaitable)
        deadline = time.monotonic() + max(0.0, bound)
        try:
            while not inner.done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log.warning("tutor hedged-turn loser cleanup timed out; dropping it")
                    inner.cancel()
                    try:
                        await inner
                    except BaseException:  # noqa: BLE001 - dropped, already logged
                        pass
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(inner), timeout=remaining)
                except TimeoutError:
                    log.warning("tutor hedged-turn loser cleanup timed out; dropping it")
                    inner.cancel()
                    try:
                        await inner
                    except BaseException:  # noqa: BLE001 - dropped, already logged
                        pass
                    break
                except asyncio.CancelledError:
                    if current is None or current.cancelling() <= before:
                        break  # the awaited side itself ended cancelled
                    continue  # our caller wants out; the close still finishes
                except Exception:
                    break  # the awaited side failed; its outcome is swallowed
            if not inner.cancelled():
                try:
                    inner.exception()  # retrieve, so it is never reported as lost
                except BaseException:  # noqa: BLE001 - retrieved, never lost
                    pass
        except (asyncio.CancelledError, Exception):
            pass
        after = current.cancelling() if current is not None else 0
        return after > before

    @staticmethod
    async def _stop_side(
        side: str,
        pumps: dict[str, asyncio.Task[None]],
        streams: dict[str, llm.LLMStream],
        bound: float = LOSER_CLEANUP_BOUND_S,
    ) -> bool:
        """Cancel a discarded side's pump, then close its stream (bounded).

        Ownership stays in the dicts until the cleanup has finished, and the
        cleanup is shielded up to ``bound`` even when the caller is cancelled
        (see ``_shielded_close``), then force-cancelled. Returns True when a
        caller cancellation was observed, so the caller re-raises it after
        the close.
        """
        cancelled = False
        pump = pumps.get(side)
        if pump is not None and not pump.done():
            pump.cancel()
            if await _RoutedStream._shielded_close(pump, bound=bound):
                cancelled = True
        stream = streams.get(side)
        if stream is not None:
            if await _RoutedStream._shielded_close(stream.aclose(), bound=bound):
                cancelled = True
        pumps.pop(side, None)
        streams.pop(side, None)
        return cancelled

    @staticmethod
    async def _stop_all(
        pumps: dict[str, asyncio.Task[None]],
        streams: dict[str, llm.LLMStream],
        bound: float = LOSER_CLEANUP_BOUND_S,
    ) -> bool:
        """Close every side within ``bound`` total, even when the caller is cancelled.

        Each side's cleanup is shielded up to the shared deadline (see
        ``_stop_side``), then force-cancelled. A cancellation observed along
        the way is re-raised only after every side is closed or
        force-cancelled, so no provider task is left running after the
        wrapper closes and the caller's cancellation still propagates.
        Returns True when a caller cancellation was observed (and raises
        ``CancelledError`` for the direct-call contract).
        """
        current = asyncio.current_task()
        before = current.cancelling() if current is not None else 0
        deadline = time.monotonic() + max(0.0, bound)
        for side in list(pumps):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Out of budget: force-cancel what is left without waiting.
                for s in list(pumps):
                    t = pumps.pop(s, None)
                    if t is not None and not t.done():
                        t.cancel()
                for s in list(streams):
                    streams.pop(s, None)
                break
            if await _RoutedStream._stop_side(side, pumps, streams, bound=remaining):
                pass
        for side in list(streams):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                for s in list(streams):
                    streams.pop(s, None)
                break
            if await _RoutedStream._stop_side(side, pumps, streams, bound=remaining):
                pass
        after = current.cancelling() if current is not None else 0
        if after > before:
            raise asyncio.CancelledError()
        return False
