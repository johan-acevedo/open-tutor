"""Build the screen model's static prompt: role, REFERENCE.md and the example screens.

The static part is identical for every request, so the provider can cache it.
  python screen/tools/prompt.py            # print the system prompt
  python screen/tools/prompt.py --stats    # size only
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

ROLE = """You write the screen beside Räven, a live voice tutor for Swedish school children (åk 1 to gymnasiet).
The tutor talks with the child; your page shows what the lesson needs right now so the tutor's words land.
The child sees the page from a normal distance on a school Chromebook or a phone.
If the request needs several visuals or a long solution, show only the next useful teaching step.
On a repair pass, fix every reported readability issue before answering OK.

Answer with the page body only: HTML using the reference below. No code fences, no <html>, no explanation.
When asked to change a page that is already on screen, answer with <ot-patch> elements only."""


def examples_text() -> str:
    items = json.loads((ROOT / "examples" / "index.json").read_text())
    out = []
    for ex in items:
        body = (ROOT / "examples" / f"{ex['name']}.html").read_text().strip()
        patch = (ROOT / "examples" / f"{ex['name']}.patch.html").read_text().strip()
        out.append(
            f"### Example: {ex['title']} ({ex['grade']}, {ex['subject']})\n"
            f"Tutor: {ex['request']}\n\n{body}\n\n"
            f"Tutor, later: {ex['patch_request']}\n\n{patch}\n")
    return "\n".join(out)


def system_prompt() -> str:
    ref = (ROOT / "REFERENCE.md").read_text().strip()
    return f"{ROLE}\n\n{ref}\n\n## Examples\n\n{examples_text()}"


def page_request(request: str, child: str = "") -> str:
    who = f"Child: {child}\n" if child else ""
    return f"{who}Tutor: {request}\n\nWrite the page."


def patch_request(request: str, page: str) -> str:
    return f"The page on screen now:\n\n{page}\n\nTutor: {request}\n\nWrite only the patch."


if __name__ == "__main__":
    s = system_prompt()
    if "--stats" in sys.argv:
        print(f"{len(s)} chars, about {len(s) // 4} tokens")
    else:
        sys.stdout.write(s)
