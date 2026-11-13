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
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
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
) -> str:
    """A short, log-safe explanation of the choice (never contains speech)."""
    if not has_fallback:
        return "single route"
    if preferred_ttft is None and fallback_ttft is None:
        return "neither route answered; keeping the preferred one"
    if chosen == PREFERRED:
        if preferred_ttft is None:  # unreachable, kept for clarity
            return "preferred route"
        if fallback_ttft is None:
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
        self._choice: str = PREFERRED
        self._reason = "single route" if fallback is None else "not decided yet"

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
                # to wait for the other route's answer.
                if preferred_s is not None and preferred_s <= self._prefer_within:
                    break
            preferred_ttft = self._timings.get(self._preferred_route.name)
            fallback_ttft = self._timings.get(self._fallback_route.name)
            choice = choose_route(preferred_ttft, fallback_ttft, self._prefer_within)
            reason = choice_reason(preferred_ttft, fallback_ttft, self._prefer_within, choice)
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

    def _record_choice(self) -> None:
        preferred = self._timings.get(self._preferred_route.name)
        fallback = self._timings.get(self._fallback_route.name)
        record_active(
            "llm_chosen",
            {
                "route": self.chosen_route.name,
                "model": self._current.model,
                "choice": self._choice,
                "reason": self._reason,
                "preferred": self._preferred_route.name,
                "fallback": self._fallback_route.name if self._fallback_route else None,
                "preferred_s": None if preferred is None else round(preferred, 3),
                "fallback_s": None if fallback is None else round(fallback, 3),
                "prefer_within_s": self._prefer_within,
                "warm_up_cap_s": self._warm_up_cap,
            },
        )
        log.info(
            "tutor LLM chosen %s (%s); warm-up preferred %s %s, fallback %s %s",
            self.chosen_route.name,
            self._reason,
            self._preferred_route.name,
            "did not answer" if preferred is None else f"{preferred:.2f} s",
            self._fallback_route.name if self._fallback_route else "-",
            "did not answer" if fallback is None else f"{fallback:.2f} s",
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


class _RoutedStream(llm.LLMStream):
    """Forwards one request to the chosen route, with one failover attempt.

    The wrapper itself never retries (``max_retry=0``): each route's own stream owns
    its single retry on that route, and the only extra attempt is the failover to the
    other candidate. A request that already delivered text or a tool call is not
    retried elsewhere, because the child has heard it.
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
        super().__init__(
            owner,
            chat_ctx=chat_ctx,
            tools=tools,
            conn_options=dataclasses.replace(conn_options, max_retry=0),
        )

    async def _run(self) -> None:
        target = await self._owner.pick()
        try:
            await self._forward(target, self._route_conn_options)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self._answered:
                # Something already reached the child; a second route would repeat it.
                record_active(
                    "llm_failed_after_output",
                    {"route": self._owner.route_name, "error": type(error).__name__,
                     "message": str(error)[:300]},
                )
                raise
            replacement = self._owner.failover(target, error)
            if replacement is None:
                raise
            await self._forward(
                replacement, dataclasses.replace(self._route_conn_options, max_retry=0)
            )

    async def _forward(self, target: llm.LLM, conn_options: APIConnectOptions) -> None:
        inner = target.chat(
            chat_ctx=self._chat_ctx,
            tools=self._tools,
            conn_options=conn_options,
            **self._call_kwargs,
        )
        try:
            async for chunk in inner:
                if chunk.has_response():
                    self._answered = True
                await self._event_ch.send(chunk)
        finally:
            try:
                await inner.aclose()
            except (Exception, asyncio.CancelledError):
                pass
