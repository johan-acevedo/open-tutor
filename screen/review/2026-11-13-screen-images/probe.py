"""Live image-resolution probe: Hydrogen low page writer + vision.

Real model calls (Hydrogen low, chat) and real Commons downloads for the page
and the patch; the rejection case reuses the recorded Colosseum bytes so only
the vision judgement is live. No real child data: the lesson is fictional.

Run from the repo root (needs the dev env with GEMINI_API_KEY)::

    OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env env \\
      SCREEN_MODEL=gemini-4-hydrogen SCREEN_API=chat SCREEN_REASONING=low SCREEN_THINKING= \\
      uv run --project server python screen/review/2026-11-13-screen-images/probe.py

Outputs (besides this file): unedited delivered bodies, shots at both pane
sizes, image audit files and a results.json with the added image seconds.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT))

os.environ["SCREEN_LOOK"] = "0"  # probe the image path, not the look pass

from open_tutor.screen import Screen  # noqa: E402
from screen.tools import screenkit  # noqa: E402
from screen.tools.page_images import PageImages  # noqa: E402

REVIEW_SYSTEM = ("Choose an educational image for a Swedish school child. Inspect the actual picture "
                 "with the lesson context. Return only the requested JSON decision, reason and a "
                 "text/HTML alternative if rejected.")

FIXTURES = ROOT / "screen" / "tests" / "fixtures" / "commons-images"


def recorded_transport():
    search = json.loads((FIXTURES / "search.json").read_text())
    photo = (FIXTURES / "colosseum.jpg").read_bytes()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "commons.wikimedia.org":
            return httpx.Response(200, json=search)
        return httpx.Response(200, content=photo, headers={"content-type": "image/jpeg"})

    return httpx.MockTransport(handle)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pages_dir = Path(tempfile.mkdtemp(prefix="screen-image-probe-"))
    results: dict = {"events": []}

    pane = [370, 610]
    screen = Screen({"name": "Noa", "grade": 6}, pages_dir,
                    get_pane_size=lambda: tuple(pane))
    print("model spec:", screen.model_spec(), flush=True)
    delivered: dict = {}

    def on_page(result):
        delivered["page"] = result

    def on_patch(result):
        delivered["patch"] = result

    screen.on_page = on_page
    screen.on_patch = on_patch

    # 1. A real model-written page with an image, at phone size.
    t0 = time.monotonic()
    screen.ask("Skriv en sida om Colosseum i Rom för årskurs 6. "
               "En kort text och en bild på Colosseum med ot-image query.")
    await screen.wait_idle()
    page = delivered.get("page")
    if page is None:
        print("PAGE JOB FAILED: no page delivered", flush=True)
        return 1
    page_meta = json.loads((page.directory / "meta.json").read_text())
    (out / "page.html").write_text(page.body, encoding="utf-8")
    shutil.copy(page.directory / "shot.png", out / "page-shot-370x610.png")
    shutil.copy(page.directory / "images.json", out / "images-page.json")
    results["page"] = {"model_s": page.model_s, "render_s": page.render_s,
                       "total_s": page.total_s,
                       "image_s": page_meta.get("image_s"),
                       "image_reviews": page_meta.get("image_reviews"),
                       "issues": page.issues}
    print(f"page: total {page.total_s:.1f}s image {page_meta.get('image_s')}s "
          f"reviews {len(page_meta.get('image_reviews') or [])}", flush=True)

    # 2. Same delivered body at the wide pane, for inspection.
    report = await asyncio.to_thread(
        screenkit.render, page.body, out, "page-wide", [(1000, 700)])
    (out / "page-wide-1000x700.png").rename(out / "page-shot-1000x700.png")
    results["page"]["wide"] = report["sizes"]["1000x700"]

    # 3. A patch adding a second image (Forum Romanum).
    screen.mark_visible(page.page_id)
    screen.ask("Lägg till en bild på Forum Romanum under bilden som redan finns.")
    await screen.wait_idle()
    patch = delivered.get("patch")
    if patch is None:
        print("PATCH JOB FAILED (see session log); page above still stands", flush=True)
        results["patch"] = None
    else:
        patch_meta = json.loads((patch.directory / "meta.json").read_text())
        (out / "patch.html").write_text(patch.patch, encoding="utf-8")
        shutil.copy(patch.directory / "patched.png", out / "patched-shot-370x610.png")
        shutil.copy(patch.directory / "images.json", out / "images-patch.json")
        results["patch"] = {"model_s": patch.model_s, "render_s": patch.render_s,
                            "total_s": patch.total_s,
                            "image_s": patch_meta.get("image_s"),
                            "image_reviews": patch_meta.get("image_reviews"),
                            "issues": patch.issues}
        print(f"patch: total {patch.total_s:.1f}s image {patch_meta.get('image_s')}s", flush=True)

    # 4. Mismatched-image rejection: recorded Colosseum bytes, flower lesson,
    #    live Hydrogen vision.
    reviewer = Screen({"name": "Noa", "grade": 3}, pages_dir)

    async def live_review(user: str, image: bytes | None) -> str:
        text, _ = await reviewer._call_model(REVIEW_SYSTEM, user, image)
        return text

    transport = recorded_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        flower = PageImages("Årskurs 3, maskrosens livscykel: frö, grodd, blomma, fröboll. "
                            "Sidan frågar barnen att peka ut fröbollen.",
                            live_review, time.monotonic() + 30, client=client)
        rejected_body = await flower.prepare(
            '<h1>Maskrosen</h1><ot-image id="blomma" query="Colosseum Rom" '
            'alt="Blomman vi pratar om"></ot-image>')
    results["rejection"] = {"events": flower.events, "seconds": round(flower.seconds, 2),
                            "body": rejected_body}
    (out / "rejection.json").write_text(
        json.dumps({"events": flower.events, "seconds": round(flower.seconds, 2),
                    "body": rejected_body}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("rejection decisions:", [e.get("decision") for e in flower.events], flush=True)

    results["wall_s"] = round(time.monotonic() - t0, 1)
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    await screen.aclose()
    await reviewer.aclose()
    print(f"done in {results['wall_s']}s, see {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
