"""Build the static comparison from a bench_ui_sdk run and review notes."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import shutil


CSS = """
:root {
  color-scheme: dark;
  font-family: system-ui, sans-serif;
  background: #14181f;
  color: #eef2f7;
  line-height: 1.55;
}
body { margin: 0; }
main { width: min(57rem, calc(100% - 2rem)); margin: 2.5rem auto 5rem; }
h1 { font-size: clamp(1.8rem, 5vw, 2.65rem); line-height: 1.12; }
h2 { margin-top: 2.25rem; }
h3 { margin-top: 0; }
p { max-width: 70ch; }
a { color: #99deff; }
img { display: block; width: 100%; height: auto; border-radius: .6rem; }
.pair { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.card { min-width: 0; padding: .85rem; background: #202731; border: 1px solid #465569; border-radius: .8rem; }
.highlight { border-left: .25rem solid #79dbb6; padding-left: .9rem; }
dl { margin: .6rem 0 0; }
dl div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .15rem 1rem; }
dd { margin: 0; font-variant-numeric: tabular-nums; text-align: right; }
ul { padding-left: 1.35rem; }
.chart { max-width: 42rem; display: grid; gap: 1rem; }
.chart h3 { margin: 0; font-size: 1rem; }
.bar-row { display: grid; grid-template-columns: 6.5rem 1fr 5rem; align-items: center; gap: .5rem; }
.track { background: #293442; height: .8rem; border-radius: .3rem; }
.track b { display: block; width: var(--width); height: 100%; background: #90a8c2; border-radius: inherit; }
.track .sdk { background: #79dbb6; }
.hint { color: #c1cbd7; }
@media (max-width: 38rem) {
  .pair { grid-template-columns: 1fr; }
  .card { max-width: 28rem; }
}
"""


def value(row, key, suffix=""):
    if key not in row or row[key] is None:
        return "—"
    item = row[key]
    number = f"{item:.2f}" if isinstance(item, float) else str(item)
    return escape(number + suffix)


ARMS = {"control": "Current shell", "sdk": "With UI SDK"}


def card(row, note, screenshot):
    arm = row["arm"]
    metrics = (
        ("First visible", value(row, "first_visible_s", " s")),
        ("Fully visible", value(row, "complete_s", " s")),
        ("Model HTML", f'{value(row, "body_bytes")} bytes · {value(row, "body_lines")} lines'),
        ("Keyboard submission", "Reached parent frame" if row.get("keyboard", {}).get("answers") else "No message recorded"),
        ("Shell issues", str(len(row["issues"])) if "issues" in row else "—"),
        ("Clarity", escape(note.get("score", "—"))),
    )
    definition_list = "".join(f"<div><dt>{label}</dt><dd>{metric}</dd></div>" for label, metric in metrics)
    description = " ".join(part for part in (note.get("observation"), note.get("accessibility"), row.get("failure")) if part)
    alt = escape(f'{row["title"]}, {ARMS[arm]}. {note.get("alt", "")}')
    content = (f'<a href="{screenshot}"><img src="{screenshot}" '
               f'width="370" height="610" loading="lazy" alt="{alt}"></a>'
               if screenshot else "<p>Screenshot unavailable.</p>")
    return (f'<article class="card"><h3>{ARMS[arm]}</h3>{content}'
            f"<dl>{definition_list}</dl><p>{escape(description)}</p></article>")


def chart(case_rows):
    max_seconds = max((row.get("complete_s", 0) for row in case_rows), default=0) or 1
    cases = {row["case"]: row["title"] for row in case_rows}
    items = []
    for slug, title in cases.items():
        bars = []
        for row in case_rows:
            if row["case"] != slug or "complete_s" not in row:
                continue
            width = row["complete_s"] / max_seconds * 100
            arm = row["arm"]
            bars.append(
                f'<div class="bar-row"><span>{ARMS[arm]}</span>'
                f'<span class="track" aria-hidden="true"><b class="{arm}" style="--width:{width:.2f}%"></b></span>'
                f'<span>{value(row, "complete_s", " s")}</span></div>'
            )
        items.append(f"<div><h3>{escape(title)}</h3>{''.join(bars)}</div>")
    return '<div class="chart">' + "".join(items) + "</div>"


def build(run: Path, notes: dict, output: Path):
    order = ("clock", "water", "english", "history", "algebra", "physics")
    rows = [row for row in json.loads((run / "results.json").read_text())["rows"]]
    rows.sort(key=lambda row: (order.index(row["case"]), row["arm"]))
    output.mkdir(parents=True, exist_ok=True)
    shots = output / "screenshots"
    shots.mkdir(exist_ok=True)
    sections = []
    links = []
    for slug in order:
        pair = [row for row in rows if row["case"] == slug]
        if not pair:
            continue
        name = escape(pair[0]["title"])
        links.append(f'<li><a href="#{slug}">{name}</a></li>')
        cards = []
        for row in pair:
            arm = row["arm"]
            shot = run / slug / arm / "screen.png"
            href = None
            if shot.is_file():
                href = f"screenshots/{slug}-{arm}.png"
                shutil.copyfile(shot, output / href)
            cards.append(card(row, notes.get("cases", {}).get(slug, {}).get(arm, {}), href))
        grade = pair[0]["grade"]
        level = f"School year {grade}" if grade <= 9 else f"Upper secondary, year {grade - 9}"
        sections.append(
            f'<section id="{slug}"><h2 lang="sv">{name}</h2><p class="hint">{level}</p>'
            f'<div class="pair">{"".join(cards)}</div></section>'
        )
    report = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart Screen exercise comparison</title>
<style>{CSS}</style>
<main>
<h1>Smart Screen exercise comparison</h1>
<p>Six fictional Swedish homework tasks at 370 × 610 CSS pixels. The screen model and lesson request
are the same in each pair. The second arm receives a catalogue of four new exercise components.</p>
<p class="highlight">{escape(notes.get("summary", ""))}</p>
<p>{escape(notes.get("bundle", ""))}</p>
<h2>Time until fully visible</h2>
<p class="hint">Seconds from the request to full opacity in the local viewer. The provider runs once per arm.</p>
{chart(rows)}
<nav aria-label="Exercises"><h2>Exercises</h2><ul>{"".join(links)}</ul></nav>
<p class="hint">Clarity is scored out of 6 for lesson content, next action, and readability. Keyboard
submission records whether any answer reached the parent frame. The notes describe limitations in
the browser's accessibility tree and any workarounds in the exercise.</p>
{"".join(sections)}
</main>
</html>
"""
    (output / "index.html").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("notes", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    build(args.run, json.loads(args.notes.read_text()), args.output)
