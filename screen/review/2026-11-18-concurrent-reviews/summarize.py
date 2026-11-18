"""Turn results-<label>.json into the before/after table in results.md.

Run from the repo root (no network, no model, no keys):
  uv run --project server python screen/review/2026-11-18-concurrent-reviews/summarize.py
"""

from __future__ import annotations

import json
import pathlib
import statistics

OUT = pathlib.Path(__file__).parent
LABELS = ("before", "after")


def is_cancelled(event: dict) -> bool:
    return "cancelled" in (event.get("reason") or "")


def summarize(rows: list[dict]) -> dict:
    accepted = [row for row in rows if row.get("ships_image")]
    image_s = [row["image_s"] for row in rows if row.get("image_s") is not None]
    events = [event for row in rows for event in row.get("candidates", [])]
    budget_cut = [row for row in rows
                  if not row.get("ships_image")
                  and any("budget" in (event.get("reason") or "") for event in row.get("candidates", []))]
    return {"runs": len(rows), "accepted": len(accepted),
            "rate": round(100 * len(accepted) / len(rows)),
            "median_image_s": round(statistics.median(image_s), 2),
            "max_image_s": max(image_s),
            "budget_cut": len(budget_cut),
            "review_calls": len([e for e in events if not is_cancelled(e)]),
            "cancelled": len([e for e in events if is_cancelled(e)])}


def main() -> None:
    results = {label: json.loads((OUT / f"results-{label}.json").read_text()) for label in LABELS}
    for label, rows in results.items():
        print(label, json.dumps(summarize(rows), ensure_ascii=False))
    asks = []
    for row in results["after"]:
        if row["ask"] not in asks:
            asks.append(row["ask"])
    print()
    print("| Ask | before | after |")
    for ask in asks:
        cells = []
        for label in LABELS:
            runs = [row for row in results[label] if row["ask"] == ask]
            parts = []
            for row in runs:
                accepted = row.get("accepted") or {}
                verdict = ((accepted.get("title") or "")[:46] or "text fallback")
                parts.append(f"{verdict} (image {row['image_s']} s, {row['reviews']} reviews)")
            cells.append("; ".join(parts))
        print(f"| {ask} | {cells[0]} | {cells[1]} |")


if __name__ == "__main__":
    main()
