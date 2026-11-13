"""Five real page jobs, with an old-look control on each identical first render.

Sequential calls only. The control runs after delivery and is NOT included in
the real job total. It is always second, so cache/provider drift can favour it.
  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env uv run --project server python screen/tools/bench_page_budget.py --out /tmp/page-budget-before
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "server"))
from open_tutor.screen import Screen

ASK = "Eleven räknar 3/4 + 1/8. Visa bara nästa steg för att förstå åttondelar och en svarsruta. Ingen bild, markering eller text får avslöja summan innan eleven svarat."


async def run(out: pathlib.Path, count: int, legacy: bool):
    rows = []
    for number in range(1, count + 1):
        folder = out / str(number)
        folder.mkdir(parents=True, exist_ok=True)
        screen = Screen({"name": "Test", "grade": 6}, folder, session_id=f"budget-{number}",
                        get_pane_size=lambda: (721, 636))
        screen.add_turn("child", "Jag förstår inte hur man lägger ihop bråk med olika nämnare.")
        delivered, failures, calls, first = [], [], [], {}
        screen.on_page, screen.on_failure = delivered.append, failures.append

        async def model(system, user, images, look_png):
            started = time.monotonic()
            text = await asyncio.to_thread(screen._default_model_call, system, user, images, look_png)
            calls.append({"kind": "look" if look_png else "retry" if "still reports these problems" in user else "page",
                          "seconds": round(time.monotonic() - started, 3), "input_chars": len(user),
                          "output_chars": len(text), "image_bytes": len(look_png or b"")})
            return text

        async def render(body, patch, width, height):
            png, issues = await screen._default_render_page(body, patch, width, height)
            if not first:
                first.update(body=body, png=png, issues=issues)
                (folder / "first.html").write_text(body)
                (folder / "first.png").write_bytes(png)
            return png, issues

        screen._model_call, screen._render_page = model, render
        try:
            screen.ask(ASK)
            await screen.wait_idle()
            row = {"run": number, "calls": calls, "failures": failures}
            if delivered:
                result = delivered[0]
                row.update(model_s=result.model_s, look_s=result.look_s, retry_s=result.retry_s,
                           render_s=result.render_s, total_s=result.total_s, issues=result.issues)
            if legacy and first:
                user = (f"The tutor's ask was: {ASK}\n\nYour page rendered like the screenshot. "
                        f"The shell reports these issues: {', '.join(str(i) for i in first['issues']) or 'none'}.\n\n"
                        "If the page looks good, answer with exactly: OK\n"
                        "Otherwise answer with the corrected full page body only (no explanation).")
                answer, duration = await screen._call_model(screen.system_prompt(), user, first["png"])
                (folder / "legacy-look.txt").write_text(answer)
                row.update(legacy_look_s=duration, legacy_chars=len(answer), legacy_input_chars=len(user))
            rows.append(row)
            (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            print(json.dumps({key: value for key, value in row.items() if key != "calls"}, ensure_ascii=False), flush=True)
        finally:
            await screen.aclose()


def profile(out: pathlib.Path):
    """One diagnostic stream: distinguish waiting for text from writing HTML."""
    from openai import OpenAI
    from open_tutor.config import USER_AGENT
    from open_tutor.screen import SCREEN_BASE_URL

    screen = Screen({"name": "Test", "grade": 6}, out / "profile", get_pane_size=lambda: (721, 636))
    screen.add_turn("child", "Jag förstår inte hur man lägger ihop bråk med olika nämnare.")
    client = OpenAI(api_key=os.environ["OPENCODE_GO_API_KEY"], base_url=SCREEN_BASE_URL,
                    timeout=25, max_retries=0, default_headers={"User-Agent": USER_AGENT, "x-opencode-session": "budget-profile"})
    started = time.monotonic()
    first, usage, count = None, {}, 0
    stream = client.chat.completions.create(model=os.environ.get("SCREEN_MODEL", "deepseek-v4.1-flash"),
        reasoning_effort="low", stream=True, stream_options={"include_usage": True},
        messages=[{"role": "system", "content": screen.system_prompt()}, {"role": "user", "content": screen._build_user_text(ASK)}])
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage.model_dump()
        for choice in chunk.choices:
            if choice.delta.content:
                first = first if first is not None else time.monotonic() - started
                count += len(choice.delta.content)
    report = {"first_text_s": first, "total_s": time.monotonic() - started, "output_chars": count, "usage": usage}
    (out / "profile.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--legacy-look", action="store_true")
    parser.add_argument("--profile-only", action="store_true")
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('--out must be empty; keep each provider run as separate evidence')
    args.out.mkdir(parents=True, exist_ok=True)
    if args.profile_only:
        profile(args.out)
    else:
        asyncio.run(run(args.out, args.count, args.legacy_look))
