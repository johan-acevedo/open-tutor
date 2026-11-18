"""Live comparison: sequential candidate reviews vs concurrent ones, 2026-11-18.

Same scripted page body for every ask (one `<ot-image query>` slot, phone pane
370x610), the same dev settings (`SCREEN_IMAGES=commons+parallel`), real
Commons and Parallel fast searches, real bounded downloads, real vision review
(Gemini 4 Hydrogen low, as dev), real shell render. Only the checkout under
test differs: `before` is `origin/main` (reviews candidates one after another),
`after` is the branch that reviews the top few at once.

Run it twice, once per checkout, from the repo root (never prints keys). The
checkout to import comes from `OPEN_TUTOR_REVIEW_ROOT`:

  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \\
    OPEN_TUTOR_REVIEW_ROOT=/tmp/open-tutor-before \\
    uv run --project /tmp/open-tutor-before/server \\
    python screen/review/2026-11-18-concurrent-reviews/compare.py before

  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \\
    uv run --project server \\
    python screen/review/2026-11-18-concurrent-reviews/compare.py after

Saves `runs/<ask>/<label>-<n>/` (body, shot, images.json, row.json) and
`results-<label>.json` next to this script. No transcript text is ever saved:
the asks are fictional and the child turns are made up.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(os.environ.get("OPEN_TUTOR_REVIEW_ROOT") or
                    pathlib.Path(__file__).resolve().parents[3]).resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))
from open_tutor.screen import Screen  # noqa: E402

OUT = pathlib.Path(__file__).parent

# The six asks of the 2026-11-18 parallel-images comparison, plus the two that
# failed in real use: a historical map of the Swedish Empire and a plain flower.
ASKS = [
    {"id": "king-gustav-ii-adolf",
     "ask": "Eleven läser om stormaktstiden. Visa ett porträtt av Gustav II Adolf med en rad om vem han var.",
     "child": "Jag vet inte vem Gustav II Adolf var.",
     "heading": "Gustav II Adolf", "query": "Gustav II Adolf portrait painting",
     "alt": "Porträtt av Gustav II Adolf",
     "caption": "Gustav II Adolf (1594–1632), kung av Sverige."},
    {"id": "king-gustav-vasa",
     "ask": "Eleven läser om Vasatiden. Visa ett porträtt av Gustav Vasa med en rad om vem han var.",
     "child": "Vem var Gustav Vasa?",
     "heading": "Gustav Vasa", "query": "Gustav Vasa portrait painting",
     "alt": "Porträtt av Gustav Vasa",
     "caption": "Gustav Vasa (1496–1560), Sveriges kung."},
    {"id": "colosseum",
     "ask": "Eleven läser om Romarriket. Visa en bild av Colosseum med en rad om vad det var.",
     "child": "Vad var Colosseum för något?",
     "heading": "Colosseum", "query": "Colosseum Rome exterior photo",
     "alt": "Colosseum i Rom", "caption": "Colosseum i Rom, byggt för gladiatorspel."},
    {"id": "flower",
     "ask": "Eleven läser om blommans delar i åk 4. Visa en bild av en maskros med en rad om blomman.",
     "child": "Hur ser en maskros ut?",
     "heading": "Maskrosen", "query": "dandelion flower close-up photo",
     "alt": "En maskros i blom", "caption": "Maskrosen blommar med gula korgblommor."},
    {"id": "water-cycle",
     "ask": "Eleven läser om vattnets kretslopp. Visa en illustration av kretsloppet.",
     "child": "Jag förstår inte vattnets kretslopp.",
     "heading": "Vattnets kretslopp", "query": "water cycle diagram illustration for children",
     "alt": "Illustration av vattnets kretslopp",
     "caption": "Vattnet rör sig mellan hav, moln och land."},
    {"id": "roman-empire-map",
     "ask": "Eleven läser om Romarriket. Visa en historisk karta över riket när det var som störst.",
     "child": "Hur stort var Romarriket?",
     "heading": "Romarriket", "query": "Roman Empire greatest extent historical map",
     "alt": "Karta över Romarriket",
     "caption": "Riket runt Medelhavet för cirka 2000 år sedan."},
    {"id": "swedish-empire-map-1658",
     "ask": "Eleven läser om stormaktstiden. Visa en riktig historisk karta över det svenska riket 1658.",
     "child": "Hur såg Sverige ut på 1600-talet?",
     "heading": "Sverige 1658", "query": "Swedish Empire map 1658 historical",
     "alt": "Historisk karta över svenska riket 1658",
     "caption": "Sverige och dess provinser vid mitten av 1600-talet."},
    {"id": "a-flower",
     "ask": "Eleven frågar vad en blomma är. Visa en bild av en blomma.",
     "child": "Kan du visa en blomma?",
     "heading": "En blomma", "query": "flower",
     "alt": "En blomma", "caption": "En blomma har kronblad, ståndare och pistill."},
]

REPEATS = 2


def body_for(item):
    return (f"<h1>{item['heading']}</h1>"
            f"<ot-image query=\"{item['query']}\" alt=\"{item['alt']}\"></ot-image>"
            f"<p>{item['caption']}</p>")


async def run_one(item, label, run_number):
    folder = OUT / "runs" / item["id"] / f"{label}-{run_number}"
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["SCREEN_IMAGES"] = "commons+parallel"
    screen = Screen({"name": "Test", "grade": 6}, folder, session_id=f"{label}-{item['id']}-{run_number}",
                    get_pane_size=lambda: (370, 610))
    screen.add_turn("child", item["child"])
    delivered, failures = [], []
    screen.on_page, screen.on_failure = delivered.append, failures.append

    async def writer(system, user, images, look_png, on_text=None, on_first_text=None):
        if images or look_png:
            # Vision review / look / retry: the real model, as in production.
            return await screen._default_model_call(system, user, images, look_png)
        # Stream the page like the real writer so the prefetch pool resolves
        # the slot while "writing", as in production.
        body = body_for(item)
        parts = [body[:len(body) // 3], body[len(body) // 3:2 * len(body) // 3], body[2 * len(body) // 3:]]
        if on_first_text is not None:
            on_first_text()
        for part in parts:
            if on_text is not None:
                on_text(part)
            await asyncio.sleep(0.5)
        return body

    screen._model_call = writer
    try:
        started = time.monotonic()
        screen.ask(item["ask"])
        await screen.wait_idle()
        wall = round(time.monotonic() - started, 2)
        row = {"ask": item["id"], "label": label, "run": run_number, "wall_s": wall,
               "failures": [str(f)[:200] for f in failures]}
        if delivered:
            result = delivered[0]
            (folder / "body.html").write_text(result.body, encoding="utf-8")
            (folder / "shot.png").write_bytes(result.png)
            row.update(total_s=round(result.total_s, 2), issues=[str(i)[:200] for i in result.issues])
            meta = json.loads((result.directory / "meta.json").read_text(encoding="utf-8"))
            images = meta.get("images", {})
            reviews = images.get("reviews", [])
            (folder / "images.json").write_text(json.dumps(reviews, ensure_ascii=False, indent=1),
                                                encoding="utf-8")
            row["strategy"] = images.get("strategy")
            row["image_s"] = images.get("seconds")
            row["review_concurrency"] = images.get("review_concurrency")
            row["reviews"] = len(reviews)
            accepted = [event for event in reviews if event.get("decision") == "accepted"]
            row["accepted"] = None
            if accepted:
                winner = accepted[0]
                row["accepted"] = {"image_source": winner.get("image_source"),
                                   "title": (winner.get("title") or "")[:80],
                                   "rank": winner.get("rank"),
                                   "served": winner.get("served_as") or winner.get("source"),
                                   "reason": (winner.get("reason") or "")[:160]}
            row["candidates"] = [
                {"rank": event.get("rank"), "title": (event.get("title") or "")[:60],
                 "decision": event.get("decision"),
                 "source": event.get("image_source"),
                 "download_s": event.get("download_s"), "review_s": event.get("review_s"),
                 "finished_s": event.get("finished_s"),
                 "reason": (event.get("reason") or "")[:120]}
                for event in reviews]
            row["ships_image"] = "<ot-image" in result.body
        (folder / "row.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: row.get(key) for key in
                          ("ask", "label", "run", "image_s", "total_s", "reviews", "ships_image")}
                         | {"accepted": (row.get("accepted") or {}).get("title")},
                         ensure_ascii=False), flush=True)
        return row
    finally:
        await screen.aclose()


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "after"
    rows = []
    for item in ASKS:
        for run_number in range(1, REPEATS + 1):
            rows.append(await run_one(item, label, run_number))
    (OUT / f"results-{label}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                                               encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
