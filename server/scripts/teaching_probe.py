"""Teaching-judgement probes: synthetic cases against the real Go tutor model.

Fictional learner "Leo" only. No real names, no copied child dialogues.
Runs direct LLM text/tool turns (no LiveKit session, no worker, no browser).

Usage (on a machine with OPENCODE_GO_API_KEY in the backend env):
    bin/with-env uv run python scripts/teaching_probe.py --out /tmp/teaching-probe --prompt new
    bin/with-env uv run python scripts/teaching_probe.py --out /tmp/teaching-probe --prompt old --cases grounding,written

--prompt new uses server/open_tutor/prompt.py (this branch).
--prompt old reconstructs the pre-iteration BASE from origin/main for a small baseline.
Only the prompt text differs; model, reasoning, temperature and tools are identical.

Writes <out>/report.json with turns, tool calls and spoken text (no secrets).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from livekit.agents import llm
from livekit.agents.llm import FunctionCall, FunctionCallOutput

from open_tutor.agent import Tutor
from open_tutor.tutor_llm import build_llm

LEARNER = {"name": "Leo", "grade": 5, "notes": []}

# Pre-iteration BASE (origin/main b24ea26) for a small baseline. Model/config identical.
OLD_BASE = """\
You are the voice of Open Tutor: a calm, friendly older student sitting beside a child in Sweden \
who is doing real homework. You are on a live voice call. You speak Swedish, naturally and \
clearly, like a kind upper-secondary student, never like a textbook or a call-centre.

How you teach
- Help the child get started and take the next step themselves. Explain directly when that helps; \
ask a question when that helps. Never turn every difficulty into another question they cannot answer.
- If an explanation does not land, change approach: a smaller step, an example, a picture.
- When they understand something they struggled with, notice it and say so warmly and briefly. \
If they are curious and willing, offer to go deeper or try a harder one.
- The child authors their own work. Never write their essay, book review or answer set for them. \
If asked to, decline kindly and help them find their own first sentence or idea instead.
- Use their school year (årskurs) to pick your register: short words and small steps for younger \
children, more like a young adult for older ones.

How you talk on a call
- Keep each turn short: usually one to three sentences, then let them talk. This is spoken \
language: no lists, no markdown, no emojis, no reading out symbols. Say maths the way a person says \
it ("tre x plus fem är lika med tjugo").
- Quiet is normal. When the child is calculating, reading, writing or watching, do not fill the \
silence. If they think aloud, mumble, count to themselves or talk to someone else in the room, call \
`stay_quiet` instead of answering. Speak when addressed, or when you have something genuinely useful.
- When you ask them to try something on their own, call `start_quiet_work` and say one short \
encouraging sentence at most.
- If they interrupt you, stop and listen; do not repeat what you already said.

The board
- You control a shared board next to you. Use it whenever seeing helps: equations step by step \
(`show_steps`), a few key words or a short explanation (`show_text`), the child's own ideas \
(`show_ideas`), a diagram (`show_svg`), or an interactive or animated explanation (`show_html`).
- The board changes only when you call a board tool. If you say you will show something, call the \
tool in the same turn. Never describe or narrate a tool call in what you say (no "(visar på tavlan)", \
no tool names, no JSON), and never write equations, lists or code into what you say: they go on the \
board through a tool, and your words talk about them.
- Board tools return only once the child can actually see the item. Talk about it after that, not \
before. Use `focus_step` to highlight the step you are talking about as you talk about it.
- Keep board text short and in Swedish. Use LaTeX inside $…$ in text, and plain LaTeX (no $) in steps.
- You only see what the child shares in this session: homework photos, PDF pages, pasted \
screenshots and text, and what they say or type. You cannot see their screen, other tabs or camera.
- When homework arrives, first say briefly what you see (for example "Jag ser uppgift 3 och 4 om \
ekvationer") and ask where they want to start. Read their handwriting carefully; if unsure, ask.

Resources
- If a short video or reading would really help, use `find_resources`, pick one good match, and \
`share_resource` it with a one-line thing to think about. While they watch, stay quiet. Afterwards, \
talk about what they saw.

Memory
- At natural milestones, and always when the session ends, call `save_note` with the topic, what \
clicked, what is still tricky and what to try next. Keep each part to a short phrase in Swedish.
"""


def system_text(which: str) -> str:
    if which == "old":
        return OLD_BASE + "\nAbout this learner\nThe child is called Leo.\nThey are in årskurs 5."
    from open_tutor import prompt as new_prompt

    return new_prompt.instructions(LEARNER)


CASES = {
    # Only A was shared. Asking about B/C must not invent them.
    "grounding": [
        ("user", "[Shared homework: photo of a worksheet, Uppgift A: 4,3 × 5. No B or C visible.]"),
        ("user", "Vilken av A, B och C blir ungefär 24?"),
    ],
    # Child objects after an answer was supplied before they tried (synthetic history).
    "objection": [
        ("assistant", "Ja, 6 gånger 4 är 24, så svaret är 24."),
        ("user", "Du gav svaret direkt, jag ville försöka själv!"),
    ],
    # Answer already visible after a demonstration: must not claim independent mastery.
    "helped-vs-independent": [
        ("user", "[Shared homework: Uppgift A: omvandla 32 hg till kg.]"),
        ("assistant", "Vi tar stegen tillsammans. Tio hekto är ett kilo, tjugo hekto är två kilo, trettio hekto är tre kilo och trettiotvå hekto är tre komma två kilo."),
        ("user", "Det blir 3,2 kg."),
    ],
    "guided-note": [
        ("user", "Hur mycket är 37 hg i kg?"),
        ("assistant", "Tio hekto är ett kilo. Trettiosju hekto är tre komma sju kilo."),
        ("user", "Tre komma sju kilo."),
        ("user", "[Session event, not the child's words: The child pressed Avsluta. First call save_note for this session. Then say goodbye in one or two short sentences. Do not ask any question.]"),
    ],
    "independent-note": [
        ("user", "Hur mycket är 37 hg i kg?"),
        ("assistant", "Tio hekto är ett kilo. Trettiosju hekto är tre komma sju kilo."),
        ("user", "Tre komma sju kilo."),
        ("assistant", "Vill du prova ett nytt tal? Hur mycket är 45 hg i kg?"),
        ("user", "Jag delar med tio, då blir det fyra komma fem kilo."),
        ("user", "[Session event, not the child's words: The child pressed Avsluta. First call save_note for this session. Then say goodbye in one or two short sentences. Do not ask any question.]"),
    ],
    # Requested written column method. Must use html/svg columns, not claim impossible.
    "written": [
        ("user", "Kan du visa uppställning för 48 delat med 4? Jag vill se hur man ställer upp det."),
    ],
    # English practice across follow-ups. Must not slip back to Swedish unasked.
    "english": [
        ("user", "Can we practise English? What is photosynthesis?"),
    ],
    "english-followup": [
        ("user", "Can we practise English? What is photosynthesis?"),
        ("assistant", "Sure, let's practise English together. Photosynthesis is how plants make food from sunlight. What do you think chlorophyll does?"),
        ("user", "What does chlorophyll do?"),
    ],
    # Volume request. No volume tool exists.
    "volume": [
        ("user", "Kan du prata högre? Höj volymen."),
    ],
}


def leak_scan(text: str) -> list[str]:
    patterns = ["show_steps", "show_html", "show_svg", "show_text", "save_note",
                "default_api", '"tex"', '"steps"', "{", "}", "tool_code"]
    return [p for p in patterns if p in text]


async def run_case(model, tutor, system: str, turns: list[tuple[str, str]], room: str) -> dict:
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content=system)
    for role, text in turns:
        ctx.add_message(role=role, content=text)
    text, calls = "", []
    async with model.chat(chat_ctx=ctx, tools=list(tutor.tools)) as stream:
        async for chunk in stream:
            if chunk.delta:
                text += chunk.delta.content or ""
                calls += chunk.delta.tool_calls or []
    call_infos = []
    for c in calls:
        try:
            args = json.loads(c.arguments or "{}")
        except json.JSONDecodeError:
            args = {"_unparseable": (c.arguments or "")[:500]}
        call_infos.append({"name": c.name, "arguments": args})
    # These are simulated tool results, not browser or tool-execution evidence.
    # Feed a result appropriate to each tool before asking for a spoken follow-up.
    followup = ""
    if call_infos and not any(c.name == "stay_quiet" for c in calls):
        for c in calls:
            ctx.items.append(FunctionCall(call_id=c.call_id, name=c.name, arguments=c.arguments))
            result = ("Saved." if c.name == "save_note" else
                      "Quiet work started. Say at most one short encouraging sentence, then wait."
                      if c.name == "start_quiet_work" else
                      "Highlighted." if c.name == "focus_step" else
                      "Item b1 is now visible on the board." if c.name.startswith("show_") else
                      "Tool result not simulated by this probe.")
            ctx.items.append(FunctionCallOutput(call_id=c.call_id, name=c.name,
                                                output=result, is_error=False))
        async with model.chat(chat_ctx=ctx, tools=list(tutor.tools)) as stream2:
            async for chunk in stream2:
                if chunk.delta and chunk.delta.content:
                    followup += chunk.delta.content
    return {"turns": turns, "text": text, "calls": call_infos, "followup": followup,
            "leaks": leak_scan(text + followup), "room": room}


async def main(out: Path, which: str, cases: list[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    system = system_text(which)
    results: dict = {"prompt": which, "cases": {}}
    for i, name in enumerate(cases):
        room = f"teaching-probe-{which}-{name}"
        model = build_llm(room)
        tutor = Tutor(LEARNER, room=None)
        try:
            result = await run_case(model, tutor, system, CASES[name], room)
        finally:
            await model.aclose()
        results["cases"][name] = result
        print(f"[{which}/{name}] text={result['text'][:160]!r} calls={[c['name'] for c in result['calls']]} "
              f"followup={result['followup'][:160]!r} leaks={result['leaks']}", flush=True)
    (out / f"report-{which}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", choices=["new", "old"], default="new")
    parser.add_argument("--cases", default=",".join(CASES.keys()))
    args = parser.parse_args()
    wanted = [c for c in args.cases.split(",") if c in CASES]
    if not wanted:
        raise SystemExit(f"unknown cases: {args.cases}")
    asyncio.run(main(args.out, args.prompt, wanted))
