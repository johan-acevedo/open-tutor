"""Tutor-turn speed test: the production prompt and tools, fictional replay of a case.

The conversation is a fictional retelling of a real shape of lesson (unit circle,
two learners at one screen): the learner is "Testbarn", the friend is "Kompis",
all lines are paraphrased. No real child's name or words are in this file.

Measures per request: time to first output (text or tool call), time to first
text, total time, and what the model did. A reply that is only tool calls gets
the tool outputs back and a second request, until the model speaks (max 3
rounds); first_text is the first speech.

Usage (from the repo root; keys come from the environment only):
    server/bin/with-env uv run --project server python server/scripts/bench_tutor_speed.py \\
        --out /tmp/tutor-bench/speed_results.json --runs 3
    server/bin/with-env uv run --project server python server/scripts/bench_tutor_speed.py \\
        --out /tmp/tutor-cc.json --runs 1 --filter "Spark 1.3 C · CC"

Keys (never printed or committed): OPENCODE_GO_API_KEY, GEMINI_API_KEY,
COMMAND_CODE_API_KEY. Only the filtered models are called, but every key the
filter selects must be present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics as st
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit.agents import llm
from livekit.agents.types import APIConnectOptions

from open_tutor import agent
from open_tutor.config import LLMRoute
from open_tutor.tutor_llm import build_route_llm

GO = "https://opencode.ai/inference/go/openai/v1"
CC = "https://api.commandcode.ai/provider/v1"
GEM = "https://generativelanguage.googleapis.com/v1beta/openai/"
go_key, gem_key, cc_key = (os.environ.get(k, "") for k in ("OPENCODE_GO_API_KEY", "GEMINI_API_KEY", "COMMAND_CODE_API_KEY"))

MODELS = [
    # label, route
    ("Muse Spark 1.3 C · Go · minimal (prod 'go')", LLMRoute("go", "responses", GO, "muse-spark-1.3-contributor", go_key, "minimal")),
    ("Muse Spark 1.3 C · CC · minimal (backup 'cc')", LLMRoute("cc", "responses", CC, "meta/muse-spark-1.3-contributor", cc_key, "minimal")),
    ("Gemini 4 Hydrogen · Google · low (prod 'gemini')", LLMRoute("gemini", "chat", GEM, "gemini-4-hydrogen", gem_key, "low", True)),
    ("DeepSeek V4.1 Flash · Go · default (prod fallback)", LLMRoute("go-deepseek", "chat", GO, "deepseek-v4.1-flash", go_key, None)),
    ("DeepSeek V4.1 Flash · CC · default", LLMRoute("cc", "chat", CC, "deepseek/deepseek-v4.1-flash", cc_key, None)),
    ("DeepSeek V4.1 Flash Fast · CC · default", LLMRoute("cc", "chat", CC, "deepseek/deepseek-v4.1-flash-fast", cc_key, None)),
    ("DeepSeek V4.1 Flash Ultrafast · CC · default", LLMRoute("cc", "chat", CC, "deepseek/deepseek-v4.1-flash-ultrafast", cc_key, None)),
    ("Muse Ember · CC · low", LLMRoute("cc", "chat", CC, "meta/muse-ember", cc_key, "low")),
    ("GLM 5.3 Flash · Go · none", LLMRoute("go-glm", "chat", GO, "glm-5.3-flash", go_key, "none")),
    ("GLM 5.3 Flash CC · low", LLMRoute("cc", "chat", CC, "z-ai/glm-5.3-flash", cc_key, "low")),
]

U, A = "user", "assistant"
EV = "[Session event] "
HISTORY = [
    (A, "Hej hej Testbarn, Räven här! Jag hjälper dig med läxor och skoluppgifter, så vad jobbar du med idag?"),
    (U, "Jag undrar om du kan visa sinus och cosinus på något sätt, typ rita upp det."),
    (A, "Absolut, vi ritar upp det! Tänker du mest på enhetscirkeln eller på en vanlig rätvinklig triangel?"),
    (U, "Ingen aning."),
    (U, EV + "Page p1 'Sinus och cosinus' is ready: unit circle with radius 1, angle v, the point (cos v, sin v), and a right triangle under it. Shown to the child."),
    (U, "Kolla. Okej, kan du förklara hur man ska se det här? Kanske göra något interaktivt?"),
    (A, "Ja! Tänk så här: cirkeln har radien ett, så linjen från mitten till punkten är alltid ett lång. När du drar upp vinkeln v är cosinus hur långt åt höger punkten ligger och sinus hur högt upp den är. Testa knapparna för vinklarna."),
    (U, EV + "The child pressed the angle button 90° on page p2."),
    (U, "Det funkar inte, vinklarna som man trycker på gör ingenting."),
    (A, "Förlåt, knapparna är inte kopplade till själva bilden. Men nu när du valde nittio grader: om vi vrider upp punkten rakt upp, vad blir x och y då?"),
    (U, "Då blir x noll och y ett. Så cosinus är noll och sinus är ett."),
    (A, "Precis så! Vid nittio grader blir cosinus noll och sinus ett. Vill du testa en annan vinkel?"),
    (U, "Nej men min kompis fattade inte. Kan du rita det tydligare, när det är nittio grader?"),
    (U, EV + "Page p2 'Sinus och cosinus vid 90°' is ready and shown: the radius points straight up to (0, 1), x-distance 0 marked, height 1 marked."),
    (A, "Här ser ni vid nittio grader pekar radien rakt upp till punkten noll komma ett. Den går inget åt sidan, så cosinus är noll, och den når hela vägen upp, så sinus är ett."),
    (U, "Inte riktigt. Jag tror inte han fattade. Kan man dra i punkten?"),
    (A, "Jag kan tyvärr inte göra punkten dragbar här. Vill ni att jag letar fram en kort animation där man ser punkten gå runt cirkeln?"),
    (U, "Ja, varför inte."),
    (U, EV + "Resource b1 shared on the board: a short video animating the point around the unit circle with the sine and cosine graphs."),
    (A, "Härligt! Blev det tydligare för er båda när ni såg hur punkten rör sig runt cirkeln?"),
    (U, "Ja, jag fattar, det ska motsvara en rät vinkel."),
]
CASES = {
    "A_agree": "Kolla, v är vinkeln här, hypotenusan är alltid ett. Så cosinus v är den här sidan och sinus v är den motstående. Om v är 90 grader är sinus ett och cosinus noll. Och om v är noll grader ligger den platt, så cosinus är ett och sinus noll. Räven, håller du med om det?",
    "B_draw": "Min kompis vill se det igen. Kan du rita upp en ny sida där man ser vinkeln noll grader och nittio grader bredvid varandra, tydligt?",
}


class _Screen:
    def set_pane_source(self, fn): pass


async def one(model, instructions, tools, user_text):
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content=instructions)
    for role, text in HISTORY:
        ctx.add_message(role=role, content=text)
    ctx.add_message(role="user", content=user_text)
    t0 = time.perf_counter(); first = first_text = None; text = ""; calls = []; err = None; rounds = 0
    # Like the worker: a reply that is only tool calls gets the tool outputs back and a
    # second request, until the model speaks (max 3 rounds). first_text = first speech.
    try:
        while rounds < 3:
            rounds += 1
            got = []
            stream = model.chat(chat_ctx=ctx, tools=tools, conn_options=APIConnectOptions(max_retry=0, timeout=30))
            async with stream:
                async for ch in stream:
                    d = ch.delta
                    if d is None:
                        continue
                    if (d.content or d.tool_calls) and first is None:
                        first = time.perf_counter() - t0
                    if d.content:
                        if first_text is None:
                            first_text = time.perf_counter() - t0
                        text += d.content
                    for c in d.tool_calls or []:
                        calls.append(c.name); got.append(c)
            if first_text is not None or not got:
                break
            for c in got:
                ctx.items.append(llm.FunctionCall(call_id=c.call_id, name=c.name, arguments=c.arguments, extra=c.extra or {}))
                out = ("The screen is working on it now (job s3). Keep talking with the child in words."
                       if c.name == "ask_screen" else "Saved." if c.name == "save_note" else "")
                ctx.items.append(llm.FunctionCallOutput(call_id=c.call_id, name=c.name, output=out, is_error=False))
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:120]}"
    total = time.perf_counter() - t0
    return {"first": first, "first_text": first_text, "total": total, "calls": calls, "chars": len(text), "rounds": rounds, "err": err}


async def main(out: Path, runs: int, models) -> None:
    tutor = agent.SmartTutor({"name": "Testbarn", "grade": 12}, MagicMock(), board={}, screen=_Screen())
    instructions, tools = tutor.instructions, list(tutor.tools)
    built = [(label, build_route_llm(route, f"bench-{i}")) for i, (label, route) in enumerate(models)]
    results = {label: {c: [] for c in CASES} for label, _ in built}
    for r in range(runs):
        order = built if r % 2 == 0 else list(reversed(built))
        for label, model in order:
            for case, text in CASES.items():
                res = await one(model, instructions, tools, text)
                results[label][case].append(res)
                print(f"run{r+1} {case} {label[:40]:40} first={res['first'] and round(res['first'],2)} text={res['first_text'] and round(res['first_text'],2)} total={res['total']:.2f} calls={res['calls']} chars={res['chars']} {res['err'] or ''}", flush=True)
    for _, model in built:
        try:
            await model.aclose()
        except Exception:
            pass
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    print("\nSUMMARY (seconds; median / max over runs; errors)")
    for label, cases in results.items():
        for case, rs in cases.items():
            ok = [x for x in rs if not x["err"] and x["first"] is not None]
            f = [x["first"] for x in ok]; sp = [x["first_text"] for x in ok if x["first_text"] is not None]
            did = {}
            for x in ok:
                k = ",".join(x["calls"]) or "text"; did[k] = did.get(k, 0) + 1
            nan = float("nan")
            print(f"{label:52} {case:8} first-output {st.median(f) if f else nan:5.2f}  first-speech med {st.median(sp) if sp else nan:5.2f} max {max(sp) if sp else nan:5.2f}  silent {len(ok)-len(sp)}  errors {len(rs)-len(ok)}  did {did}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("speed_results.json"), help="results JSON file to write")
    parser.add_argument("--runs", type=int, default=5, help="runs per model and case")
    parser.add_argument("--filter", default="", help="only models whose label contains this (case-insensitive)")
    args = parser.parse_args()
    selected = [m for m in MODELS if args.filter.lower() in m[0].lower()]
    if not selected:
        parser.error(f"--filter {args.filter!r} matches no model")
    asyncio.run(main(args.out, args.runs, selected))
