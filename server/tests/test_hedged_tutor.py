"""Hedged tutor turns: a slow primary loses the race, the child hears one reply.

Each turn starts on the current primary route. With hedging on and safe (both
routes ignore thought signatures), the same request also starts on the other
route past a short deadline; the first stream to yield a chunk wins, the loser
is cancelled, and nothing is forwarded before the winner is decided. A secondary
route that wins twice running becomes the primary (sticky preference).
"""

import asyncio

import pytest
from livekit.agents import llm
from livekit.agents.llm import FunctionToolCall
from livekit.agents.types import APIConnectOptions

from open_tutor.config import LLMRoute
from open_tutor.session_llm import SessionLLM, choice_reason, tutor_hedge_after_s


def route(name: str, *, signatures: bool = False) -> LLMRoute:
    return LLMRoute(
        name=name, api="chat", base_url="http://fake", model=f"{name}-model",
        api_key="k", reasoning_effort=None, thought_signatures=signatures,
    )


class ScriptedStream(llm.LLMStream):
    """A provider stream from a script: (delay, text) chunks, then an optional error."""

    def __init__(self, owner, chat_ctx, tools, conn_options, *, script, error=None) -> None:
        super().__init__(owner, chat_ctx=chat_ctx, tools=tools,
                         conn_options=conn_options or APIConnectOptions())
        self._script = list(script)
        self._error = error
        self.closed = False

    async def _run(self) -> None:
        for delay, payload in self._script:
            if delay:
                await asyncio.sleep(delay)
            if isinstance(payload, FunctionToolCall):
                delta = llm.ChoiceDelta(role="assistant", content=None, tool_calls=[payload])
            else:
                delta = llm.ChoiceDelta(role="assistant", content=payload)
            await self._event_ch.send(llm.ChatChunk(id="c1", delta=delta))
        if self._error is not None:
            raise self._error

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


class HedgeFakeLLM(llm.LLM):
    """An LLM whose answer per call is scripted; every stream is kept for assertions."""

    def __init__(self, model: str, *, script=None, error=None) -> None:
        super().__init__()
        self._model = model
        self.script = list(script or [(0.01, "Hej")])
        self.error = error
        self.calls = 0
        self.streams: list[ScriptedStream] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider(self) -> str:
        return "fake"

    def chat(self, *, chat_ctx=None, tools=None, conn_options=None, **kwargs):
        self.calls += 1
        stream = ScriptedStream(self, chat_ctx or llm.ChatContext(), tools or [],
                                conn_options, script=list(self.script), error=self.error)
        self.streams.append(stream)
        return stream


@pytest.fixture
def hedged(monkeypatch):
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "0.05")
    return "0.05"


@pytest.fixture
def turns(monkeypatch):
    import open_tutor.session_llm as session_llm

    events = []
    monkeypatch.setattr(session_llm, "record_active",
                        lambda event, data=None: events.append((event, data or {})))
    return events


def llm_turns(events):
    return [data for event, data in events if event == "llm_turn"]


async def warmed(preferred, fallback, preferred_route=None, fallback_route=None):
    model = SessionLLM(preferred, preferred_route or route("preferred"),
                       fallback, fallback_route or route("fallback"),
                       prefer_within=1.5)
    await model.warm_up(instructions="Du är Räven.", tools=[])
    return model


async def run_turn(model):
    stream = model.chat(chat_ctx=llm.ChatContext())
    try:
        text = ""
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                text += chunk.delta.content
        return text
    finally:
        await stream.aclose()


# ---- the deadline ------------------------------------------------------------


def test_hedge_after_defaults_and_disables(monkeypatch):
    monkeypatch.delenv("TUTOR_LLM_HEDGE_AFTER_S", raising=False)
    assert tutor_hedge_after_s() == 2.5
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "")
    assert tutor_hedge_after_s() is None
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "0")
    assert tutor_hedge_after_s() is None
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "1.25")
    assert tutor_hedge_after_s() == 1.25
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "junk")
    assert tutor_hedge_after_s() == 2.5


def test_choice_reason_distinguishes_not_awaited_from_failed():
    assert choice_reason(0.4, None, 1.5, "preferred", not_awaited={"fallback"}) == \
        "preferred route answered within 1.5 s; other route not awaited"
    # A fallback that errored is a real non-answer, not an early end of the race.
    assert choice_reason(0.4, None, 1.5, "preferred") == "only the preferred route answered"


async def test_warm_up_marks_the_cancelled_route_not_failed(turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.02, "Hej")])
    fallback = HedgeFakeLLM("fallback", script=[(5.0, "Hej")])
    model = SessionLLM(preferred, route("preferred"), fallback, route("fallback"),
                       prefer_within=1.5)
    result = await model.warm_up(instructions="Du är Räven.", tools=[])

    assert result["route"] == "preferred"
    assert result["not_awaited"] == ["fallback"]
    chosen = [data for event, data in turns if event == "llm_chosen"]
    assert len(chosen) == 1
    assert chosen[0]["fallback_s"] is None
    assert chosen[0]["fallback_not_awaited"] is True
    assert "not awaited" in chosen[0]["reason"]
    await asyncio.sleep(0.1)  # let the cancelled backup warm-up land


# ---- the race -----------------------------------------------------------------


async def test_no_hedge_when_the_primary_is_fast(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.01, "snabb")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "backup")])
    model = await warmed(preferred, fallback)

    assert await run_turn(model) == "snabb"
    assert fallback.calls == 1  # the warm-up only: the backup never raced
    (turn,) = llm_turns(turns)
    assert turn["primary"] == "preferred" and turn["winner"] == "preferred"
    assert turn["hedged"] is False and turn["loser"] == "none"
    assert turn["ttft_s"] is not None and turn["ttft_s"] < 0.2


async def test_hedge_fires_and_the_faster_secondary_wins(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.5, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback)

    assert await run_turn(model) == "fast"  # no mixed reply: nothing of "slow" leaks
    assert fallback.calls == 2  # warm-up plus the hedged turn
    assert preferred.streams[-1].closed  # the loser is closed, nothing left running
    (turn,) = [t for t in llm_turns(turns)]
    assert turn["primary"] == "preferred" and turn["winner"] == "fallback"
    assert turn["hedged"] is True and turn["loser"] == "cancelled"
    assert 0.04 < turn["ttft_s"] < 0.4
    assert "primary_ttft_s" not in turn  # the primary never answered before the cancel


async def test_primary_wins_after_the_hedge_started(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.1, "primary")])
    fallback = HedgeFakeLLM("fallback", script=[(0.4, "late")])
    model = await warmed(preferred, fallback)

    assert await run_turn(model) == "primary"
    assert fallback.streams[-1].closed  # the late backup is cancelled and closed
    (turn,) = llm_turns(turns)
    assert turn["winner"] == "preferred" and turn["hedged"] is True
    assert turn["loser"] == "cancelled"


async def test_first_tool_call_wins_the_race(hedged, turns):
    call = FunctionToolCall(name="ask_screen", arguments="{}", call_id="c1")
    preferred = HedgeFakeLLM("preferred", script=[(0.5, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, call)])
    model = await warmed(preferred, fallback)

    stream = model.chat(chat_ctx=llm.ChatContext())
    try:
        tools = []
        async for chunk in stream:
            tools += [c.name for c in (chunk.delta.tool_calls if chunk.delta else None) or []]
    finally:
        await stream.aclose()
    assert tools == ["ask_screen"]  # the tool call, not the slow text, reached the child
    (turn,) = llm_turns(turns)
    assert turn["winner"] == "fallback" and turn["hedged"] is True


async def test_one_error_before_any_chunk_lets_the_other_win(hedged, turns):
    preferred = HedgeFakeLLM("preferred")
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "backup")])
    model = await warmed(preferred, fallback)
    preferred.script = []
    preferred.error = RuntimeError("primary down")

    assert await run_turn(model) == "backup"
    (turn,) = llm_turns(turns)
    assert turn["winner"] == "fallback" and turn["loser"] == "error"


async def test_both_erroring_raises_todays_error(hedged, turns):
    preferred = HedgeFakeLLM("preferred")
    fallback = HedgeFakeLLM("fallback")
    model = await warmed(preferred, fallback)
    preferred.script = []
    preferred.error = RuntimeError("primary down")
    fallback.script = []
    fallback.error = RuntimeError("secondary down")

    with pytest.raises(RuntimeError, match="primary down"):
        await run_turn(model)
    (turn,) = llm_turns(turns)
    assert turn["winner"] is None and turn["error"] == "RuntimeError"


async def test_gemini_route_never_hedges(hedged, turns):
    import time

    preferred = HedgeFakeLLM("preferred")
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback,
                         preferred_route=route("gemini", signatures=True),
                         fallback_route=route("plain"))
    preferred.script = [(0.3, "slow")]

    started = time.monotonic()
    assert await run_turn(model) == "slow"  # the backup never raced
    assert time.monotonic() - started >= 0.25
    assert fallback.calls == 1  # the warm-up only
    (turn,) = llm_turns(turns)
    assert turn["hedged"] is False and turn["winner"] == "gemini"


async def test_hedging_off_keeps_todays_behaviour(monkeypatch, turns):
    monkeypatch.setenv("TUTOR_LLM_HEDGE_AFTER_S", "0")
    preferred = HedgeFakeLLM("preferred", script=[(0.2, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback)

    assert await run_turn(model) == "slow"
    assert fallback.calls == 1
    (turn,) = llm_turns(turns)
    assert turn["hedged"] is False


# ---- sticky preference ---------------------------------------------------------


async def test_secondary_wins_twice_becomes_primary(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.3, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback)

    assert await run_turn(model) == "fast"
    assert model.route_name == "preferred"  # one win is not enough
    assert await run_turn(model) == "fast"
    assert model.route_name == "fallback"  # two in a row: sticky switch
    switches = [data for event, data in turns if event == "llm_sticky_switch"]
    assert len(switches) == 1
    assert switches[0]["from"] == "preferred" and switches[0]["to"] == "fallback"


async def test_sticky_switch_is_symmetric(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.3, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback)
    await run_turn(model)
    await run_turn(model)
    assert model.route_name == "fallback"

    # Now the old secondary is the slow one: two wins switch straight back.
    fallback.script = [(0.3, "slow now")]
    preferred.script = [(0.01, "fast again")]
    assert await run_turn(model) == "fast again"
    assert model.route_name == "fallback"  # only one win so far
    assert await run_turn(model) == "fast again"
    assert model.route_name == "preferred"
    switches = [data for event, data in turns if event == "llm_sticky_switch"]
    assert [(s["from"], s["to"]) for s in switches] == [
        ("preferred", "fallback"), ("fallback", "preferred")]


async def test_primary_win_resets_the_streak(hedged, turns):
    preferred = HedgeFakeLLM("preferred", script=[(0.3, "slow")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "fast")])
    model = await warmed(preferred, fallback)
    await run_turn(model)  # secondary wins once
    preferred.script = [(0.01, "fast now")]
    await run_turn(model)  # primary wins: the streak resets
    preferred.script = [(0.3, "slow")]
    await run_turn(model)  # secondary wins once more: still no switch
    assert model.route_name == "preferred"
    assert not [event for event, _ in turns if event == "llm_sticky_switch"]


# ---- analytics -----------------------------------------------------------------


async def test_hedge_summary_counts_turns_per_route(hedged):
    preferred = HedgeFakeLLM("preferred", script=[(0.01, "snabb")])
    fallback = HedgeFakeLLM("fallback", script=[(0.01, "backup")])
    model = await warmed(preferred, fallback)
    await run_turn(model)
    await run_turn(model)
    preferred.script = [(0.3, "slow")]
    await run_turn(model)  # hedged: the fallback wins

    summary = model.hedge_summary_for_analytics()
    assert summary["llm_turns_total"] == 3
    assert summary["llm_hedged_turns"] == 1
    assert summary["llm_sticky_switches"] == 0
    assert summary["llm_routes"]["preferred"]["turns_won"] == 2
    assert summary["llm_routes"]["fallback"]["turns_won"] == 1
    for stats in summary["llm_routes"].values():
        assert stats["median_ttft_s"] is not None and stats["max_ttft_s"] is not None


def test_empty_turn_list_summarizes_to_zero():
    from open_tutor.analytics import summarize_llm_turns

    assert summarize_llm_turns([]) == {"turns_total": 0, "hedged_turns": 0, "routes": {}}
    assert summarize_llm_turns(None) == {"turns_total": 0, "hedged_turns": 0, "routes": {}}

