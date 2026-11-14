"""Smart Screen model comparison: the real page pipeline, a real-world ask.

The ask is the tutor's first ask_screen from a real 13 Nov lesson (tutor-written,
no child words). The learner is fictional ("Testbarn"). Each job runs the
production Screen (write, render, lint, look, retry); only the model call is
swapped so providers outside the worker config can take part. The job timeout is
raised from 20 s to 90 s so slow pages are still judged; total_s above 20 means
production would have failed the job.

What ran on 2026-11-14: 7 models x 2 reasoning levels (\"lo\" = lowest accepted,
\"hi\" = one step up), 3 runs each, blind-judged on the rendered pages. See
docs/smart-screen.md (\"Model bake-off (2026-11-14)\") for the method and results.

Usage (from the repo root; keys come from the environment only):
    server/bin/with-env uv run --project server python screen/tools/bench_screen_models.py \\
        --out /tmp/screen-models --runs 3
    server/bin/with-env uv run --project server python screen/tools/bench_screen_models.py \\
        --out /tmp/screen-spark --only spark-lo,spark-hi --runs 1

Keys (never printed or committed): OPENCODE_GO_API_KEY, GEMINI_API_KEY,
COMMAND_CODE_API_KEY -- whichever the selected configs need.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "server"))

from open_tutor.config import USER_AGENT
from open_tutor.screen import Screen

GO = "https://opencode.ai/inference/go/openai/v1"
CC = "https://api.commandcode.ai/provider/v1"
GEM = "https://generativelanguage.googleapis.com/v1beta/openai/"
KEYS = {GO: "OPENCODE_GO_API_KEY", CC: "COMMAND_CODE_API_KEY", GEM: "GEMINI_API_KEY"}
ASK = ("En tydlig visuell sida om sinus och cosinus för gymnasiet åk 3, med både enhetscirkeln och en "
       "rätvinklig triangel så man ser hur vinkeln hänger ihop med x- och y-värden samt motstående och närliggande katet.")
PANE = (575, 571)


# (id, label, base_url, model, api, reasoning kwargs) - "lo" = lowest accepted, "hi" = one step up
def chat_effort(e): return {"reasoning_effort": e}
DS_OFF_GO = {"extra_body": {"thinking": {"type": "disabled"}}}
CONFIGS = [
    ("spark-lo", "Muse Spark 1.3 C · Go · minimal", GO, "muse-spark-1.3-contributor", "responses", "minimal"),
    ("spark-hi", "Muse Spark 1.3 C · Go · low", GO, "muse-spark-1.3-contributor", "responses", "low"),
    ("gemini-lo", "Gemini 4 Hydrogen · low (prod)", GEM, "gemini-4-hydrogen", "chat", chat_effort("low")),
    ("gemini-hi", "Gemini 4 Hydrogen · medium", GEM, "gemini-4-hydrogen", "chat", chat_effort("medium")),
    ("dsgo-lo", "DeepSeek V4.1 Flash · Go · thinking off", GO, "deepseek-v4.1-flash", "chat", DS_OFF_GO),
    ("dsgo-hi", "DeepSeek V4.1 Flash · Go · low", GO, "deepseek-v4.1-flash", "chat", chat_effort("low")),
    ("dscc-lo", "DeepSeek V4.1 Flash · CC · off", CC, "deepseek/deepseek-v4.1-flash", "chat", chat_effort("off")),
    ("dscc-hi", "DeepSeek V4.1 Flash · CC · low", CC, "deepseek/deepseek-v4.1-flash", "chat", chat_effort("low")),
    ("dsfast-lo", "DeepSeek V4.1 Flash Fast · CC · off", CC, "deepseek/deepseek-v4.1-flash-fast", "chat", chat_effort("off")),
    ("dsfast-hi", "DeepSeek V4.1 Flash Fast · CC · low", CC, "deepseek/deepseek-v4.1-flash-fast", "chat", chat_effort("low")),
    ("dsuf-lo", "DeepSeek V4.1 Flash Ultrafast · CC · off", CC, "deepseek/deepseek-v4.1-flash-ultrafast", "chat", chat_effort("off")),
    ("dsuf-hi", "DeepSeek V4.1 Flash Ultrafast · CC · low", CC, "deepseek/deepseek-v4.1-flash-ultrafast", "chat", chat_effort("low")),
    ("ember-lo", "Muse Ember · CC · low", CC, "meta/muse-ember", "chat", chat_effort("low")),
    ("ember-hi", "Muse Ember · CC · medium", CC, "meta/muse-ember", "chat", chat_effort("medium")),
    ("glm-lo", "GLM 5.3 Flash · Go · none", GO, "glm-5.3-flash", "chat", chat_effort("none")),
    ("glm-hi", "GLM 5.3 Flash · Go · minimal", GO, "glm-5.3-flash", "chat", chat_effort("minimal")),
    ("glmcc-lo", "GLM 5.3 Flash · CC · low", CC, "z-ai/glm-5.3-flash", "chat", chat_effort("low")),
    ("glmcc-hi", "GLM 5.3 Flash · CC · medium", CC, "z-ai/glm-5.3-flash", "chat", chat_effort("medium")),
]


def make_call(base_url, model, api, reasoning, session_id):
    from openai import OpenAI
    client = OpenAI(api_key=os.environ[KEYS[base_url]], base_url=base_url, timeout=85.0, max_retries=0,
                    default_headers={"User-Agent": USER_AGENT, "x-opencode-session": session_id})

    def call(system, user, images, look_png):
        image_url = None
        if look_png:
            mime = "image/jpeg" if look_png.startswith(b"\xff\xd8\xff") else "image/png"
            image_url = f"data:{mime};base64,{base64.b64encode(look_png).decode()}"
        if api == "chat":
            content = [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": u}} for u in images]
            if image_url:
                content.append({"type": "image_url", "image_url": {"url": image_url}})
            r = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system},
                                                                       {"role": "user", "content": content}], **reasoning)
            return (r.choices[0].message.content or "").strip()
        if images or image_url:
            parts = [{"type": "input_text", "text": user}] + [{"type": "input_image", "image_url": u} for u in images]
            if image_url:
                parts.append({"type": "input_image", "image_url": image_url})
            r = client.responses.create(model=model, instructions=system, input=[{"role": "user", "content": parts}],
                                        reasoning={"effort": reasoning}, store=False)
        else:
            r = client.responses.create(model=model, instructions=system, input=user,
                                        reasoning={"effort": reasoning}, store=False)
        return (r.output_text or "").strip()
    return call


async def job(out: pathlib.Path, cfg, run):
    cid, label, base, model, api, reasoning = cfg
    folder = out / cid / f"run{run}"
    folder.mkdir(parents=True, exist_ok=True)
    screen = Screen({"name": "Testbarn", "grade": 12}, folder, session_id=f"bench-{cid}-{run}",
                    get_pane_size=lambda: PANE, timeout=90.0)
    raw = make_call(base, model, api, reasoning, f"bench-{cid}-{run}")
    calls = []

    async def model_call(system, user, images, look_png):
        t = time.monotonic()
        kind = "look" if look_png else "retry" if "still reports these problems" in user else "page"
        try:
            text = await asyncio.to_thread(raw, system, user, images, look_png)
            calls.append({"kind": kind, "s": round(time.monotonic() - t, 2), "chars": len(text)})
            return text
        except Exception as e:
            calls.append({"kind": kind, "s": round(time.monotonic() - t, 2), "error": f"{type(e).__name__}: {str(e)[:150]}"})
            raise

    screen._model_call = model_call
    delivered, failures = [], []
    screen.on_page, screen.on_failure = delivered.append, failures.append
    screen.add_turn("child", "Kan du visa sinus och cosinus med en bild, så att jag ser hur det hänger ihop?")
    t0 = time.monotonic()
    try:
        screen.ask(ASK)
        await screen.wait_idle()
    finally:
        await screen.aclose()
    row = {"config": cid, "label": label, "run": run, "wall_s": round(time.monotonic() - t0, 2), "calls": calls,
           "failures": [str(f)[:200] for f in failures]}
    if delivered:
        r = delivered[0]
        (folder / "final.png").write_bytes(r.png)
        (folder / "final.html").write_text(r.body)
        row.update(delivered=True, title=r.title, model_s=round(r.model_s, 2), look_s=round(r.look_s, 2),
                   retry_s=round(r.retry_s, 2), render_s=round(r.render_s, 2), total_s=round(r.total_s, 2),
                   in_prod_budget=r.total_s <= 20.0, issues=[str(i)[:120] for i in r.issues],
                   residual=r.residual_issues, body_chars=len(r.body))
    else:
        row["delivered"] = False
    return row


async def main(out: pathlib.Path, runs: int, configs) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for run in range(1, runs + 1):
        order = configs if run % 2 else list(reversed(configs))
        for cfg in order:
            row = await job(out, cfg, run)
            rows.append(row)
            (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
            print(json.dumps({k: v for k, v in row.items() if k not in ("calls",)}, ensure_ascii=False)[:400], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=pathlib.Path, required=True, help="output directory (results.json plus per-run pages)")
    parser.add_argument("--runs", type=int, default=3, help="runs per config")
    parser.add_argument("--only", default="", help="comma-separated config ids to run (default: all)")
    args = parser.parse_args()
    wanted = {o.strip() for o in args.only.split(",") if o.strip()}
    selected = [c for c in CONFIGS if not wanted or c[0] in wanted]
    if not selected:
        parser.error(f"--only matches no config (choose from {', '.join(c[0] for c in CONFIGS)})")
    asyncio.run(main(args.out, args.runs, selected))
