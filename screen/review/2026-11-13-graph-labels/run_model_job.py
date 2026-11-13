"""One fresh Hydrogen-low page job checking how the writer responds to graph lint.

Ask (the research plan ask, unedited): rectangle 4x3 + L with side labels and a
perimeter answer box, narrow pane where crowding bites. The first attempt's label
placement is measured by the new shell; if `crowded: label ...` lint remains, the
existing bounded retry rewrites the body once. A patch then shows patch-time lint.

  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \\
    SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \\
    uv run --project server python screen/review/2026-11-13-graph-labels/run_model_job.py --out DIR

No key is printed; timing per model call is reported (12 s target, 20 s hard).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

ASK = ("Rita en rektangel som är 4 cm bred och 3 cm hög, och en L-form med måtten "
       "3 cm, 2 cm och 1 cm. Måtten ska stå vid sidorna. En svarsruta för "
       "rektangelns omkrets. Rita inget svar.")


async def main(out: Path) -> dict:
    from open_tutor.screen import Screen, strip_fences

    out.mkdir(parents=True, exist_ok=True)
    holder: dict = {}

    async def run() -> None:
        screen = Screen({"name": "Nova", "grade": 6}, out, session_id="geom-label-overlap",
                        get_pane_size=lambda: (370, 610))
        screen.add_turn("child", "Jag har prov på geometri imorgon och blandar ihop begreppen.")

        async def model(system, user, images, look_png):
            started = time.monotonic()
            text = await asyncio.to_thread(screen._default_model_call, system, user,
                                           images, look_png)
            holder.setdefault("calls", []).append(
                {"look": bool(look_png), "seconds": round(time.monotonic() - started, 2),
                 "user_chars": len(user), "answer_chars": len(text)})
            if not look_png:
                holder.setdefault("raw", text)
            return text

        screen._model_call = model
        delivered, failures = [], []
        screen.on_page, screen.on_failure = delivered.append, failures.append
        wall = time.monotonic()
        screen.ask(ASK)
        await screen.wait_idle()
        holder["wall_s"] = round(time.monotonic() - wall, 2)
        holder["failures"] = failures
        if delivered:
            result = delivered[0]
            (out / "delivered.html").write_text(result.body, encoding="utf-8")
            (out / "delivered-370x610.png").write_bytes(result.png)
            holder["residual"] = result.issues
            holder["model_s"] = result.model_s
            holder["render_s"] = result.render_s
            holder["retry_s"] = result.retry_s
        holder["raw"] = strip_fences(holder.get("raw", ""))
        (out / "ask.txt").write_text(ASK, encoding="utf-8")
        (out / "raw.html").write_text(holder["raw"], encoding="utf-8")
        await screen.aclose()

    await run()
    summary = {"ask": ASK, "wall_s": holder.get("wall_s"), "calls": holder.get("calls", []),
               "failures": holder.get("failures", []),
               "model_s": holder.get("model_s"), "render_s": holder.get("render_s"),
               "retry_s": holder.get("retry_s"),
               "residual_issues": holder.get("residual", [])}
    (out / "meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    summary = asyncio.run(main(Path(args.out)))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
