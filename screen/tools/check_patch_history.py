"""Real Chromium preview of successive patches, with synthetic inputs and no model calls.

uv run --project server python screen/tools/check_patch_history.py --out /tmp/patch-history
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
from open_tutor.screen import Screen

BODY = '<h1>Ett steg i taget</h1><p>Vi arbetar vidare på samma sida.</p><ot-answer id="svar" label="Ditt svar"></ot-answer>'
FIRST = '<ot-patch target="svar" do="before"><p id="mellansteg">Här kommer nästa steg.</p><p id="facit" later>Förklaringen kommer senare.</p></ot-patch>'
SECOND = '<ot-patch target="mellansteg"><p>Nu är det nya steget synligt.</p></ot-patch><ot-patch target="facit" do="remove"></ot-patch><ot-patch target="svar" do="remove"></ot-patch>'
BAD = '<ot-patch target="mellansteg"><p>Den här ändringen får inte skickas.</p></ot-patch><ot-patch target="missing" do="remove"></ot-patch>'


async def run(out: Path):
    report = []
    for size in ((370, 610), (1000, 700)):
        answers = iter((BODY, FIRST, SECOND, BAD))

        async def model(*args):
            return next(answers)

        folder = out / f"{size[0]}x{size[1]}"
        screen = Screen({"grade": 6}, folder, model_call=model, get_pane_size=lambda: size)
        patches, failures = [], []
        screen.on_patch, screen.on_failure = patches.append, failures.append
        try:
            screen.ask("Visa en lugn sida.")
            await screen.wait_idle()
            screen.mark_visible("p1")
            for ask in ("Lägg till nästa steg.", "Ändra steget och ta bort svarsrutan.", "Pröva en ogiltig ändring."):
                screen.ask(ask)
                await screen.wait_idle()
            entry = {"pane": size, "patches": len(patches), "failures": failures,
                     "patch_issues": [p.issues for p in patches]}
            report.append(entry)
            out.mkdir(parents=True, exist_ok=True)
            (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(entry, ensure_ascii=False))
            assert len(patches) == 2, "a bad patch reached delivery, or a valid history patch was rejected"
            assert not patches[1].issues, "the preview forgot ids added by the first patch"
            assert len(failures) == 1 and "not applied" in failures[0], "bad patch did not fail to tutor"
            assert screen.visible_patches == [FIRST, SECOND], "rejected patch polluted visible history"
        finally:
            await screen.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    import os
    os.environ["SCREEN_LOOK"] = "0"
    asyncio.run(run(args.out))
