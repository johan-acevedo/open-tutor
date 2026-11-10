# Board gym — state

Lead: Opus 5.5 medium (this thread). Branch `gym/board-renderer`. Data (private, never in git): dell5500 `~/gym-data/board-gym/`.
Progress page: http://100.91.148.43:8743 (user unit `gym-board-site.service` on dell5500).

## Goal
Each member renders excellent teaching boards fast. Targets on the hidden panel: ≥90% judged correct, clarity ≥4.5/5, median wall ≤15 s incl. any fix pass.

## Cases
- `python3 gym/ingest.py` pulls thinkcentre debug trails and makes one case per board tool call.
- 2026-11-10: 27 sessions, 17 with board moments, 109 cases (83 show_text, 16 show_steps, 6 show_svg, 4 show_html).
- Hidden = 5 frozen sessions (`gym/splits.json`, 26 cases); new sessions go hidden when sha256(room) % 4 == 0.
- Panels (deduped by session+title, rich kinds first): tune 14 cases, hidden 11 cases (`cases/panels.json`).
- Homework images are not stored by the debug trail (sizes only), so no case has an image yet.
- Each case gives the member the tutor's own draft (tool + title + content) as "what the tutor asked to show". `after` (tutor's next lines) goes to judges only.

## Members
claude-haiku-5-5, deepseek-v4.1-flash, longcat-2.5-free, muse-spark-1.3-contributor, minimax-m3.1-flash (all `pi --model opencode-go/<id>`, image input verified 2026-11-10: 3–8 s for a trivial image prompt).

## Rounds
| Round | What changed | Status |
|---|---|---|
| r0 | Baseline: plain scenario framing (`prompts/r0`), thinking low, one shot, no toolkit, palette given as information | harness being built |

## Kicks
None yet.

## Open questions / next
- Harness (run/judge/report/site): Muse worker, in progress.
