"""One fresh Hydrogen-low page job checking the length lint on real writer output.

Ask: a to-scale 3-4-5 triangle with side labels and a perimeter answer box,
narrow pane. The writer's unedited first answer is kept (raw.html); the
delivered page may carry one bounded lint retry. A patch then adds pointable
corners without touching the labels, proving patch-time lint stays quiet.
Renders at 370x610 and 1000x700 are inspected by the worker.

  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \\
    SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \\
    uv run --project server python screen/review/2026-11-13-lengths/run_model_job.py --out DIR

No key is printed; timing per model call is reported (12 s target, 20 s hard).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

ASK = ("Rita en triangel med sidorna 3 cm, 4 cm och 5 cm. Måtten ska stå vid "
       "sidorna. En svarsruta för triangelns omkrets. Rita inget svar.")
PATCH_ASK = ("Lägg till triangelns tre hörn som punkter som eleven kan peka på. "
             "Ändra inga mått.")


async def main(out: Path) -> dict:
    from open_tutor.screen import Screen, strip_fences

    out.mkdir(parents=True, exist_ok=True)
    holder: dict = {}

    async def run() -> None:
        screen = Screen({"name": "Nova", "grade": 6}, out, session_id="geom-length-lint",
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
        delivered, patches, failures = [], [], []
        screen.on_page, screen.on_patch, screen.on_failure = (
            delivered.append, patches.append, failures.append)
        wall = time.monotonic()
        screen.ask(ASK)
        await screen.wait_idle()
        holder["wall_s"] = round(time.monotonic() - wall, 2)
        holder["failures"] = failures
        if delivered:
            result = delivered[0]
            (out / "delivered.html").write_text(result.body, encoding="utf-8")
            (out / "delivered-370x610.png").write_bytes(result.png)
            holder["model_s"] = result.model_s
            holder["render_s"] = result.render_s
            holder["retry_s"] = result.retry_s
            holder["residual"] = result.issues
        holder["raw"] = strip_fences(holder.get("raw", ""))
        (out / "ask.txt").write_text(ASK, encoding="utf-8")
        (out / "raw.html").write_text(holder["raw"], encoding="utf-8")

        # One tutor follow-up on the delivered page: pointable corners, same measures.
        if delivered:
            screen.mark_visible(delivered[0].page_id)
            wall = time.monotonic()
            screen.ask(PATCH_ASK)
            await screen.wait_idle()
            holder["patch_wall_s"] = round(time.monotonic() - wall, 2)
            if patches:
                (out / "patch.html").write_text(patches[0].patch, encoding="utf-8")
                (out / "patch-370x610.png").write_bytes(patches[0].png)
                holder["patch_issues"] = patches[0].issues
            holder["patch_failures"] = [f for f in failures if f not in holder["failures"]]
        await screen.aclose()

    await run()
    summary = {"ask": ASK, "patch_ask": PATCH_ASK, "wall_s": holder.get("wall_s"),
               "patch_wall_s": holder.get("patch_wall_s"), "calls": holder.get("calls", []),
               "failures": holder.get("failures", []),
               "patch_failures": holder.get("patch_failures", []),
               "model_s": holder.get("model_s"), "render_s": holder.get("render_s"),
               "retry_s": holder.get("retry_s"),
               "residual_issues": holder.get("residual", []),
               "patch_issues": holder.get("patch_issues", [])}
    (out / "meta.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    print(json.dumps(asyncio.run(main(Path(args.out))), ensure_ascii=False, indent=1))
