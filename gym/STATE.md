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
claude-haiku-5-5, deepseek-v4.1-flash, muse-spark-1.3-contributor, minimax-m3.1-flash (longcat-2.5-free kicked after r0) (all `pi --model opencode-go/<id>`, image input verified 2026-11-10: 3–8 s for a trivial image prompt).

## Judges (decision log)
- 2026-11-10 Johan: **Muse Spark 1.3 (high) is the judge**, to spare Opus. Boards by member muse-spark also get DeepSeek v4.1 Flash (high) as a second judge, combined (correct ANDed, scores averaged), so Spark never scores its own family alone.
- Opus/Sol remain available for spot checks. Sol (Codex) hit its usage limit 2026-11-10, back 2026-11-11 09:07.
- Lead verifies a sample of each round's verdicts against the PNGs.
- Render fix 2026-11-10: judges see the *settled* board (timers fast-forwarded 15 s, finite animations finished) plus an early frame at 1.5 s. 99/125 r0 boards animate; the first r0 judging at 1.5 s was discarded. One-shot wall = model time only (render counts only with a fix pass).

- 2026-11-10 calibration (lead): 39 r0 boards (all Spark-vs-Opus/Sol disagreements + agreed sample), reference = Opus/Sol verdicts. Agreement: **Gemini 4 Argon (Go, high) 34/39**, Gemini 3.8 Flash (agy) 30, MiMo v2.6 Pro 27, DeepSeek v4.1 Flash 26, Muse Spark xhigh 22, Spark high 15. Argon+MiMo AND 35 (not worth 2x). `python3 gym/calib.py`.
- **Decision: Gemini 4 Argon is the gym judge** (rubric v2 `prompts/judge-v2.md` with written checks + layout-script evidence, 2 boards/call). No member is Google family, so no second judge. Spark judging (Johan's first choice) was too lenient: it passed a clock showing 9 when the tutor said three, hg→g ×10, clipped text.
- Gemini 3.8 Flash runs via Antigravity (`agy`, logged in on dell5500 2026-11-10) with `--sandbox --dangerously-skip-permissions` (headless mode blocks its commands otherwise).

## Rounds
| Round | What changed | Status |
|---|---|---|
| r0 | Baseline: plain framing, thinking low, one shot | done. Tune correct (Argon): Haiku 50% · DeepSeek 79% · MiniMax 43% · Spark 36%; median s: 5 · 45 · 11 · 21 |
| r1 | Space/time awareness in framing; thinking minimal for DeepSeek and Spark | done. Tune correct: Haiku 64% · DeepSeek 71% · MiniMax 43% · Spark 29%; median s: 4.6 · 37 · 14 · 11. Off-screen text boards 15→10 of 56 |
| r2 | r1 + one fix pass on layout findings (Haiku, MiniMax, Spark); DeepSeek thinking off | done. Tune correct: Haiku 71% (8.2 s) · MiniMax 64% (28 s) · Spark 50% (17 s) · DeepSeek 64% (57 s, slower with thinking off) |
| r3 | Haiku: review pass on every board. Spark + MiniMax: BoardKit library offered + fix pass on findings. DeepSeek parked | done. Tune: **Haiku 79% (14.5 s)** · Spark 57% (21 s) · MiniMax 43% (14 s). BoardKit used 1/28 times (Spark 1, MiniMax 0). Haiku hidden checkpoint running |
| r3 hidden | Haiku r3 config on the hidden panel | **Haiku hidden 82% correct, clarity 4.0, median 16.4 s** (p90 36 s) |
| r4 | All three: r1 framing + review pass on every board with a written checklist (style `checks`), no BoardKit | done. Haiku 79% (15.0 s, no gain over plain review) · Spark 64% (31 s) · MiniMax 43% (37 s) |
| r5 | r3 recipe + school-context line (Swedish written methods, notation, terms). Haiku + Spark | done. Haiku 71% (15.8 s), Spark 50% (28 s): no gain from the line |
| r6 | r5 with Haiku thinking medium (both calls) | done. **Haiku 86% correct, clarity 4.5, median 21.7 s** (first call 8.8 s) |
| r7 | r6 but review at thinking low | running |
| r8 | Haiku medium, fix pass only on layout findings | queued |

## Parked
- deepseek-v4.1-flash, after r2: best quality (r0 79% tune, r0 hidden 80%) but median 37–63 s in r0–r2; thinking minimal/off made it no faster (off: 57 s). Not kicked: may serve a non-live use. Revisit only with a new speed idea.

## Kicks
- **minimax-m3.1-flash: kicked 2026-11-10 after r4 (lead).** Tune correct 43/43/64/43/43% over r0–r4: no gain in the last 3 rounds, and with any fix or review pass its median is 28–37 s.
- **longcat-2.5-free: kicked 2026-11-10 (Johan: not stable enough).** Ignores `--thinking` (off/minimal still reason >120 s with no HTML); 18/25 r0 boards timed out at 180 s. Its r0 boards stay in the data for reference; it runs in no further round.

## Open questions / next
- Harness done (Muse worker, 05ff675) + lead fixes (434883f).
