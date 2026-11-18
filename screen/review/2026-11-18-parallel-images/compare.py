"""Live comparison: Commons vs Commons+Parallel for six image asks, 2026-11-18.

Same scripted page body under both modes; only SCREEN_IMAGES differs. Real
Parallel fast search, real Commons, real downloads, real vision review (Go
Muse Spark, as dev), real shell render at phone size. Saves per-ask body,
screenshot, images.json and meta.json next to this script.

Run from the repo root (needs provider keys through with-env; never prints them):
  OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env \\
    uv run --project server python screen/review/2026-11-18-parallel-images/compare.py
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "server"))
from open_tutor.screen import Screen

OUT = pathlib.Path(__file__).parent

ASKS = [
    {"id": "king-gustav-ii-adolf",
     "ask": "Eleven läser om stormaktstiden. Visa ett porträtt av Gustav II Adolf med en rad om vem han var.",
     "child": "Jag vet inte vem Gustav II Adolf var.",
     "heading": "Gustav II Adolf",
     "query": "Gustav II Adolf portrait painting",
     "alt": "Porträtt av Gustav II Adolf",
     "caption": "Gustav II Adolf (1594–1632), kung av Sverige."},
    {"id": "king-gustav-vasa",
     "ask": "Eleven läser om Vasatiden. Visa ett porträtt av Gustav Vasa med en rad om vem han var.",
     "child": "Vem var Gustav Vasa?",
     "heading": "Gustav Vasa",
     "query": "Gustav Vasa portrait painting",
     "alt": "Porträtt av Gustav Vasa",
     "caption": "Gustav Vasa (1496–1560), Sveriges kung."},
    {"id": "colosseum",
     "ask": "Eleven läser om Romarriket. Visa en bild av Colosseum med en rad om vad det var.",
     "child": "Vad var Colosseum för något?",
     "heading": "Colosseum",
     "query": "Colosseum Rome exterior photo",
     "alt": "Colosseum i Rom",
     "caption": "Colosseum i Rom, byggt för gladiatorspel."},
    {"id": "flower",
     "ask": "Eleven läser om blommans delar i åk 4. Visa en bild av en maskros med en rad om blomman.",
     "child": "Hur ser en maskros ut?",
     "heading": "Maskrosen",
     "query": "dandelion flower close-up photo",
     "alt": "En maskros i blom",
     "caption": "Maskrosen blommar med gula korgblommor."},
    {"id": "water-cycle",
     "ask": "Eleven läser om vattnets kretslopp. Visa en illustration av kretsloppet.",
     "child": "Jag förstår inte vattnets kretslopp.",
     "heading": "Vattnets kretslopp",
     "query": "water cycle diagram illustration for children",
     "alt": "Illustration av vattnets kretslopp",
     "caption": "Vattnet rör sig mellan hav, moln och land."},
    {"id": "roman-empire-map",
     "ask": "Eleven läser om Romarriket. Visa en historisk karta över riket när det var som störst.",
     "child": "Hur stort var Romarriket?",
     "heading": "Romarriket",
     "query": "Roman Empire greatest extent historical map",
     "alt": "Karta över Romarriket",
     "caption": "Riket runt Medelhavet för cirka 2000 år sedan."},
]


def body_for(item):
    return (f"<h1>{item['heading']}</h1>"
            f"<ot-image query=\"{item['query']}\" alt=\"{item['alt']}\"></ot-image>"
            f"<p>{item['caption']}</p>")


async def run_one(item, mode):
    folder = OUT / item["id"] / mode
    folder.mkdir(parents=True, exist_ok=True)
    os.environ["SCREEN_IMAGES"] = mode
    screen = Screen({"name": "Test", "grade": 6}, folder, session_id=f"compare-{item['id']}-{mode}",
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
        row = {"ask": item["id"], "mode": mode, "wall_s": wall,
               "failures": list(failures)}
        if delivered:
            result = delivered[0]
            (folder / "body.html").write_text(result.body, encoding="utf-8")
            (folder / "shot.png").write_bytes(result.png)
            row.update(total_s=round(result.total_s, 2), issues=[str(i) for i in result.issues])
            meta_path = folder / _latest_job_dir(folder) / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            images = meta.get("images", {})
            (folder / "images.json").write_text(
                json.dumps(images.get("reviews", []), ensure_ascii=False, indent=1), encoding="utf-8")
            row["strategy"] = images.get("strategy")
            row["image_s"] = images.get("seconds")
            row["parallel"] = images.get("parallel")
            for event in images.get("reviews", []):
                if event.get("decision") == "accepted":
                    row["accepted"] = {"image_source": event.get("image_source"),
                                       "title": (event.get("title") or "")[:80],
                                       "credit": "", "latency_s": event.get("latency_s"),
                                       "reason": (event.get("reason") or "")[:160]}
            slots = body_slots(result.body)
            row["ships_query"] = any("query=" in s for s in slots)
            row["ships_src"] = [s for s in slots if "src=" in s]
        (folder / "row.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in row.items() if k != "ships_src"}, ensure_ascii=False), flush=True)
        return row
    finally:
        await screen.aclose()


def body_slots(body):
    import re
    return re.findall(r"<ot-image[^>]*>", body)


def _latest_job_dir(folder):
    entries = sorted(folder.iterdir(), key=lambda p: p.stat().st_mtime)
    for entry in reversed(entries):
        if entry.is_dir() and (entry / "meta.json").exists():
            return entry.name
    raise RuntimeError(f"no job dir with meta.json in {folder}")


async def main():
    rows = []
    for item in ASKS:
        for mode in ("commons", "commons+parallel"):
            rows.append(await run_one(item, mode))
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
