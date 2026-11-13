# Screen images, live evidence (2026-11-13)

Live check of the server-side image path with the dev page writer
(**Gemini 4 Hydrogen, low**, chat). Fictional lessons, no real child data.
Repro: `probe.py` (see its docstring for the exact command; needs the dev env).
One run each, so treat timings as indicative.

## What ran live

| Job | Total | Image part | Outcome |
|---|---|---|---|
| Page: Colosseum, åk 6, 370×610 (1st) | 10.0 s | 2.8 s, then budget out | Text fallback, lint-clean, delivered on time |
| Page: same ask rerun | 10.0 s | 5.7 s, 1 review | **Accepted**: Colosseum evening photo, Diliff CC BY-SA 2.5 |
| Patch: add Forum Romanum | 6.1 s | 3.4 s, 1 review | **Accepted**: panorama, BeBo86 CC BY-SA 3.0, loaded before shot |
| Rejection: recorded Colosseum bytes, flower lesson, live vision | 14.2 s, 3 reviews | all rejected | Swedish reasons, text fallback with `id` kept |

Files: `page.html` / `page-shot-370x610.png` / `page-shot-1000x700.png`
(the accepted rerun), `patch.html` / `patched-shot-370x610.png`,
`images-page.json` / `images-patch.json` (audit: title, source, reason,
sha256, bytes), `rejection.json`, `results.json`.
`patched-shot-fixed-370x610.png` re-renders the recorded page+patch through
the fixed previewer; `patched-shot-370x610.png` is the pre-fix blank-image
screenshot it replaces.

## What the shots show

- `page-shot-370x610.png` and `page-shot-1000x700.png`: the accepted Diliff
  photo renders with its credit line, readable text, no lint at either size.
- `patched-shot-fixed-370x610.png`: the Forum Romanum photo is loaded in the
  preview screenshot. Before the fix (`patched-shot-370x610.png`) the same
  job screenshotted an empty box with only the credit line: `ot.patch`
  reports before patch-added images arrive, and the server shot at once.
  The previewer now holds the screenshot (bounded, 5 s) until patch-added
  bitmaps are complete, and picks up late image-load failures as issues.
- `rejection.json`: all three recorded Colosseum candidates rejected for the
  maskros lesson ("har ingenting med maskrosens livscykel att göra"), with a
  teaching fallback and the element id intact for pointing.

## Honest limits

- Image budget (6 s, inside the 12 s soft target) is shared with a slow first
  answer: the first page attempt spent 6 s generating and starved the review.
  The page still shipped in 10 s with the fallback. Only image pages pay.
- The rejection probe reviewed 3 candidates in 14.2 s; in production the same
  6 s budget would review fewer and leave the rest unaudited. Unreviewed
  candidates are never accepted: the page falls back to text.
- The fix waits for `ot-image img` completeness in the server preview only;
  the child still sees a patch at once with the photo popping in on load.
- Recorded suites (`screen/tests/test_commons_images.py`,
  `screen/tests/test_page_images.py`, `server/tests/test_screen.py`) use
  scripted vision replies: they pin the orchestration, not live judgement.
