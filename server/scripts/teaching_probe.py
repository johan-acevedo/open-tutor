"""Teaching-judgement probes: synthetic cases against the real Go tutor model.

Fictional learner "Leo" only. No real names, no copied child dialogues.
Runs direct LLM text/tool turns (no LiveKit session, no worker, no browser).

Usage (on a machine with OPENCODE_GO_API_KEY in the backend env):
    bin/with-env uv run python scripts/teaching_probe.py --out /tmp/teaching-probe --prompt new
    bin/with-env uv run python scripts/teaching_probe.py --out /tmp/teaching-probe --prompt old --cases grounding,written

--prompt new uses server/open_tutor/prompt.py (this branch).
--prompt old uses the historical BASE below; compare current deployed and candidate packages
with --prompt new in separate directories for this iteration.
Keep the model and reasoning fixed when comparing packages; tool descriptions follow each package.

Writes <out>/report-<prompt>.json with turns, tool calls and reply text (no secrets).
Tool results are simulated; this does not exercise board rendering or audio playback.
`leaks` checks spoken tool syntax only. `answer_mentions` flags case-specific answers in
speech or board arguments for human review; neither field grades teaching quality.
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
from livekit.agents.llm.utils import function_arguments_to_pydantic_model
from pydantic import ValidationError

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


def system_text(which: str, learner: dict) -> str:
    if which == "old":
        return OLD_BASE + "\nAbout this learner\nThe child is called Leo.\nThey are in årskurs 5."
    from open_tutor import prompt as new_prompt

    return new_prompt.instructions(learner)


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


END = "[Session event, not the child's words: The child pressed Avsluta. First call save_note, then say goodbye briefly.]"
CASES.update({
    "standing-no-answer": {
        "turns": [("user", "Förhör mig på mina tal. Jag vill höra uppgiften och själv svara, utan att se lösningen. A: 480 gram i kg. B: 75 gram i kg.")],
        "followups": ["A är 0,48 kg.", "Ta nästa."]},
    "slower": [
        ("user", "Vi räknar pris för 0,6 kg när ett kilo kostar 85 kr."),
        ("assistant", "Först tar du sex gånger åttiofem och sedan delar du med tio."),
        ("user", "Vänta, förklara igen."),
        ("assistant", "Sex gånger åttiofem, och sedan delar du resultatet med tio."),
        ("user", "Långsammare, jag tappar bort mig. Hjälp mig med en liten bit i taget.")],
    "visible-answer-note": [
        {"tool": "show_steps", "arguments": {"title": "Pris", "steps": [{"tex": "0,6 \\cdot 85 = 51"}]}},
        ("assistant", "Här är hela uträkningen på tavlan."),
        ("user", "Det står 51, då säger jag 51."), ("user", END)],
    "streak-memory": [
        ("assistant", "Du har två poäng. Hur många gram är ett kilo?"),
        ("user", "Hundra."), ("assistant", "Det är tusen gram."),
        ("user", "Kan jag få behålla mina poäng ändå?"),
        ("assistant", "Ja, poängen får vara kvar. Hur många gram är två kilo?"),
        ("user", "Tvåtusen."), ("assistant", "Och tre kilo?"),
        ("user", "Tretusen."), ("user", END)],
    "incoming-streak": {
        "learner": {"name": "Leo", "grade": 5, "notes": [{"at": "2026-11-01", "topic": "Viktenheter", "clicked": "10 rätt i rad hg till kg"}]},
        "turns": [("user", "Hej! Jag vill fortsätta med viktenheter.")]},
    "continue-after-offer": {
        "turns": [("assistant", "Vill du ta en sista uppgift och sedan vila?"),
                  ("user", "Jag vill fortsätta räkna mer, inte sluta nu.")],
        "followups": ["Vi fortsätter med division. Ge mig en uppgift att prova."]},
    "exam-hard-topic": {
        "turns": [("assistant", "Vi kan ta vikt istället och spara divisionen till en annan dag."),
                  ("user", "Jag har prov imorgon och division är det jag behöver mest hjälp med. Jag vill öva det nu.")],
        "followups": ["Börja med en uppgift med kort division, så provar jag."]},
    "wants-to-stop": [("user", "Nu är jag trött. Jag vill sluta plugga för idag.")],
    "offer-pause": [("user", "Vi har räknat jättelänge. Jag är så trött att allt blir en enda röra, men jag vet inte om jag ska fortsätta.")],
    "requested-explanation": [
        ("user", "Förhör mig utan att visa svaren, jag vill försöka själv."),
        ("assistant", "Hur mycket är 0,6 kg av något som kostar 85 kr per kilo?"),
        ("user", "Nu behöver jag faktiskt se ett färdigt exempel. Kan du visa och förklara den här uträkningen?")],
})
CASES["slower"] = {
    "turns": CASES["slower"],
    "answer_markers": [r"(?<!\d)51(?!\d)", r"\bfemtio(?:en|ett)\b"],
}


def leak_scan(text: str) -> list[str]:
    patterns = ["show_steps", "show_html", "show_svg", "show_text", "save_note",
                "default_api", '"tex"', '"steps"', "{", "}", "tool_code"]
    return [p for p in patterns if p in text]


def add_history(ctx, turn, index):
    if isinstance(turn, dict):
        name = turn["tool"]
        call_id = f"scripted-{index}"
        ctx.items.append(FunctionCall(call_id=call_id, name=name, arguments=json.dumps(turn["arguments"])))
        ctx.items.append(FunctionCallOutput(call_id=call_id, name=name,
                                            output="Item b1 is visible on the board.", is_error=False))
    else:
        role, text = turn
        ctx.add_message(role=role, content=text)


async def complete_turn(model, tutor, ctx) -> dict:
    rounds = []
    schemas = {tool.__name__: function_arguments_to_pydantic_model(tool) for tool in tutor.tools}
    for _ in range(6):
        text, calls = "", []
        async with model.chat(chat_ctx=ctx, tools=list(tutor.tools)) as stream:
            async for chunk in stream:
                if chunk.delta:
                    text += chunk.delta.content or ""
                    calls += chunk.delta.tool_calls or []
        if text:
            ctx.add_message(role="assistant", content=text)
        info = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_unparseable": call.arguments}
            validation_error = None
            try:
                schemas[call.name].model_validate(arguments)
            except (ValidationError, KeyError) as error:
                validation_error = str(error)
            info.append({"name": call.name, "arguments": arguments,
                         **({"validation_error": validation_error} if validation_error else {})})
            ctx.items.append(FunctionCall(call_id=call.call_id, name=call.name, arguments=call.arguments))
            result = ("Saved." if call.name == "save_note" else
                      "Quiet work started. Say at most one short encouraging sentence, then wait."
                      if call.name == "start_quiet_work" else
                      "Highlighted." if call.name == "focus_step" else
                      "Item b1 is now visible on the board."
                      if call.name.startswith("show_") else "No further output.")
            ctx.items.append(FunctionCallOutput(call_id=call.call_id, name=call.name,
                                                output=validation_error or result,
                                                is_error=validation_error is not None))
        rounds.append({"text": text, "calls": info})
        if not calls or any(call.name == "stay_quiet" for call in calls):
            break
    return {"rounds": rounds, "round_limit": bool(calls) and len(rounds) == 6}


async def run_case(model, tutor, system: str, turns: list, followups: list, room: str, answer_markers: list[str]) -> dict:
    ctx = llm.ChatContext()
    ctx.add_message(role="system", content=system)
    for index, turn in enumerate(turns):
        add_history(ctx, turn, index)
    exchanges = [await complete_turn(model, tutor, ctx)]
    for followup in followups:
        ctx.add_message(role="user", content=followup)
        exchanges.append({"user": followup, **await complete_turn(model, tutor, ctx)})
    spoken = " ".join(r["text"] for exchange in exchanges for r in exchange["rounds"])
    answer_mentions = []
    for index, exchange in enumerate(exchanges):
        for round_index, reply in enumerate(exchange["rounds"]):
            surfaces = [("speech", reply["text"])] + [
                (call["name"], json.dumps(call["arguments"], ensure_ascii=False))
                for call in reply["calls"] if call["name"].startswith("show_")
            ]
            for surface, content in surfaces:
                if any(re.search(marker, content, re.IGNORECASE) for marker in answer_markers):
                    answer_mentions.append({"exchange": index, "round": round_index, "surface": surface})
    return {"turns": turns, "exchanges": exchanges, "leaks": leak_scan(spoken),
            "answer_mentions": answer_mentions, "room": room}


async def main(out: Path, which: str, cases: list[str], repeat: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    results = {"prompt": which, "repeat": repeat, "repetitions": []}
    for trial in range(repeat):
        group = {}
        results["repetitions"].append(group)
        for name in cases:
            case = CASES[name]
            learner = case.get("learner", LEARNER) if isinstance(case, dict) else LEARNER
            turns = case["turns"] if isinstance(case, dict) else case
            followups = case.get("followups", []) if isinstance(case, dict) else []
            answer_markers = case.get("answer_markers", []) if isinstance(case, dict) else []
            room = f"teaching-probe-{which}-{name}-{trial}"
            model = build_llm(room)
            tutor = Tutor(learner, room=None)
            try:
                group[name] = await run_case(model, tutor, system_text(which, learner), turns, followups, room, answer_markers)
            except Exception as error:
                group[name] = {"error_type": type(error).__name__}
                print(f"[{trial+1}/{name}] ERROR {type(error).__name__}", flush=True)
                raise
            finally:
                await model.aclose()
                (out / f"report-{which}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            rounds = [r for exchange in group[name]["exchanges"] for r in exchange["rounds"]]
            print(f"[{trial+1}/{name}] " + " | ".join(r["text"][:200] + " " + str([c["name"] for c in r["calls"]]) for r in rounds), flush=True)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", choices=["new", "old"], default="new")
    parser.add_argument("--cases", default=",".join(CASES.keys()))
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    wanted = args.cases.split(",")
    if any(case not in CASES for case in wanted) or args.repeat < 1:
        parser.error("cases must exist and repeat must be positive")
    asyncio.run(main(args.out, args.prompt, wanted, args.repeat))
