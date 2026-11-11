# Board gym — state

Lead: **Muse Spark 1.3 Contributor xhigh** from 2026-11-10 evening (handed over from Opus 5.5, whose quota ran out). Branch `gym/board-renderer`. Data (private, never in git): dell5500 `~/gym-data/board-gym/`.
Progress page: http://100.91.148.43:8743 (user unit `gym-board-site.service` on dell5500).

## Goal
Each member renders excellent teaching boards fast. Targets on the hidden panel: ≥90% judged correct, clarity ≥4.5/5, median wall ≤20 s incl. any fix pass (Johan 2026-11-10: 20 s can work; was 15 s).
Focus from 2026-11-10: **Haiku 5.5 only** (Johan: narrow down on Haiku and iterate on it).

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
- **Decision: Gemini 4 Argon is the gym judge** (rubric v2 `prompts/judge-v2.md` with written checks + layout-script evidence, 2 boards/call). ~80 s per 14-board round. No member is Google family, so no second judge. Spark judging (Johan's first choice) was too lenient: it passed a clock showing 9 when the tutor said three, hg→g ×10, clipped text.
- 2026-11-11: Kimi 3.1 Pro trial as judge (backend added, `--judge kimi`): re-judged r18 tune, **13/14 agreement with Argon in ~95 s**. Sole disagreement (Pythagoras board): Argon failed it (label overlap + unrequested quiz box), Kimi passed; lead checked the PNG — Kimi arguably right, and r18 allows interactivity. Not a full calibration (39 boards vs Opus/Sol); Argon stays official, Kimi second opinion.
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
| r7 | r6 but review at thinking low | done. Haiku 71% (18.6 s) |
| r8 | Haiku medium, fix pass only on layout findings (9/14 triggered) | done. Haiku 71% (19.4 s, p90 49 s) |
| r9 | r6 + Swedish-convention reference examples in framing (kort division with raised remainder, minnessiffra/"1 i minne", unit staircase with unit names, terms). One new variable | done tune. **92.9% (13/14), clarity 4.5, median 24.0 s.** All 4 r6b Swedish-convention fails now pass (verified on PNGs: "1 i minne" + minnessiffra shown; no Anglo bracket); the 1 fail is a layout nit (caption flush at left edge). Correct ✓, clarity ✓, speed ✗ (24 vs 20 s target) |
| r9 hidden | r9 config checkpoint on the hidden panel | done. **72.7% (8/11), clarity 4.1, median 21.7 s.** 20 pts below tune. Lead verified 2/3 fails on PNGs, both fair: a real place-value error (tens digit 6 called "ental") and overlapping remainder digits in decimal kort division; third is wording/diagram. Examples fixed notation but harder hidden cases still slip factually |
| r10 | r9 but review pass at thinking high (one new variable), to catch residual factual/wording errors | done tune. **64.3%, clarity 3.9, median 22.0 s — much worse.** Fails even repeat the example topics ("1 l × 10 -> 1 dl", "tonne", "Ett steg ner = ×10"). Review level is non-monotonic: low (r7: 71%) and high both worse than medium. Likely reviewer overthinking + run noise |
| r11 | Exact repeat of r9 tune, to measure spread at the top end (is r9's 92.9 luck like r6's 86 was?) | done. **78.6%, clarity 3.9, median 22.0 s** — yes, partly luck. r9-config tune range 79–93, r6-config 64–86: ±15 pts noise on n=14, nothing smaller is signal. True level ≈ high-70s/low-80s tune, 73–82 hidden |
| r12 | r9 recipe but fix pass only on layout findings (no always-review): does quality hold without the review time cost? | done tune. **85.7%, clarity 4.0, median 14.7 s (p90 27.6).** Quality held (in noise band), speed target met. Both fails are unit-staircase cases — the examples' staircase section not fully landing |
| r12 hidden | r12 config checkpoint on the hidden panel — decides the deliverable | done. **63.6% (7/11), clarity 4.0, median 22.8 s.** 22 pts below tune — systematic, not noise (r9: same 20-pt gap). Verified on PNG: board states 1 hg = 100 g yet labels the arrow ×10 and a blanket "Ett steg ner: ×10" rule. Our own example's blanket ×10 rule is causing it. Staircase/unit fails: 2/3 r9-hidden + 2/4 r12-hidden |
| r13 | r12 with sharpened staircase example (per-step factor from the equality, hg→g ×100, ton/kg/hg/g only, no dekagram). One new variable | done tune. **85.7%, clarity 4.2, median 17.9 s.** Both fails now staircase *layout* (covered box, arrow direction), no factual errors — facts fixed, layout remains |
| r13 hidden | r13 config checkpoint on hidden: does the staircase fix transfer? | done. **72.7% (8/11), clarity 3.9, median 19.9 s.** Staircase factual errors gone; remaining fails are overlap/layout (verified 1 on PNG: genuinely broken — fair). Same 73% as r9 hidden. Three hidden checkpoints, no gain over r3's 82%: stopping per the stop rule |
| r14 | r13 + component toolkit appendix (KaTeX, JSXGraph, Chart.js pinned copy-exact snippets; use-only-if-better + never-guess-API rules). Tests Johan's hypothesis: competent components beat bare-bones HTML. Watch adoption rate + JS-error fails + wall time (cold CDN load overstates cost vs warm production) | done tune. **71.4%, clarity 4.0, median 12.3 s.** Adoption 1/14 (KaTeX once, passed). One fail is a dropped digit ("+ 2,8" for "+ 23,8", verified on PNG — fair). Toolkit mostly unused; score in noise band vs 85.7 |
| r15 | Broad optional toolkit (Johan): r14 + Leaflet + Three.js snippets; OSM/CARTO tiles allowlisted in render+lint. Curriculum-wide, use-when-it-helps (not scoped to gym math cases) | done tune. **64.3%, clarity 3.9, median 14.8 s.** Adoption 1/14. Bigger prompt + toolkit trending down (85.7 → 71.4 → 64.3): appendix distracts on math cases |
| r16 | Diagnostic (Johan): r15 + Haiku appends reasoning note after </html> (choices + toolkit use/why-not). Timing ignored; goal = quality + insight into its decisions. Runs alongside r15 (1 call in flight each) | done tune. **64.3%, clarity 3.9.** Notes: toolkit deliberately unused — "ren HTML räckte" + faster than an API it is unsure of. Notes in Swedish, children named — good situational awareness |
| r17 | Johan-philosophy rewrite (prompts/r11): situation + inventory only — no Swedish examples, no toolkit rules, open internet, dynamic board/device/lang placeholders (run.py fills [[..]] from config). Heads-up vs r13 | done tune. **64.3%, clarity 3.9.** Swedish errors return without the examples ('Gånger och dela', 'gång med 10'). Freedom alone does not match r13 |
| r18 | Johan r18: style = bg + font only, interactive boards allowed, compact API docs inlined per lib, reasoning at length. Tests whether API knowledge unlocks toolkit use | done tune. **78.6%, clarity 4.1, median 19.0 s.** Best freedom round; one fail is an unrequested interactive quiz box |
| r19 | DeepSeek v4.1-flash (ultrafast) on latest prompt (r12), thinking off, argon judge | running (tune only) |
| r20 | Same model via Fireworks ultrafast router (smoke test 0.5 s). Heads-up vs r19 | STOPPED by Johan 2026-11-11 (cost; do not use Fireworks until he says so). 5/14 boards at ~15-18 s before stop; 12/12 initial fails were the thinking-parse bug, fixed mid-round |
| r21 | Adopted prompt-review edits (prompts/r13: settled-immediately, ≥18px, tutor-leads line, conventions one-liner, textcolor tip). DeepSeek opencode-go. Clock single-board manual test first | running (clock case) |

## Deliverable (2026-11-11 ~01:30, lead Muse Spark)
- **Winning config: r13** (`gym/configs/r13.yaml`, framing `gym/prompts/r7`): Haiku 5.5, Swedish-convention reference examples (kort division with raised remainder, minnessiffra/"1 i minne", unit staircase with per-step factor from the equality, ton/kg/hg/g only), thinking medium, fix pass only on layout-script findings.
- **Evidence:** tune 85.7% (12/14) twice (r12, r13), clarity 3.9–4.3, median wall 14.7–17.9 s; hidden 63.6–72.7% (r12h, r13h), clarity ~4.0, median ~20–23 s. Per-round grids: `/round-r12.html`, `/round-r13.html`.
- **Targets:** speed ✓ (tune ≤18 s, hidden ~20 s); correctness ✗ (need 90%, have ~73% hidden / ~86% tune); clarity ✗ (need 4.5, have ~4.0–4.3).
- **Production recommendation:** ship the r13 recipe (examples + medium + findings-only review) as the board renderer; show the first board immediately and keep the current no-swap behaviour — findings-only review costs ~15 s median, acceptable against the 20 s budget, but its layout lint misses overlaps (r13 hidden Y6-b2), so keep always-review as a fallback for layout-flagged cases. Do NOT use review at thinking high/low (both worse than medium). Next vectors if correctness must rise: (1) bigger panels — n=11/14 cannot resolve anything under ~15 pts, so build more cases (homework images when the tutor log stores them); (2) best-of-2 first boards; (3) layout-lint upgrade to catch overlaps (r13 Y6-b2 slipped through); (4) Sol independent check of the final hidden verdicts (Sol back 2026-11-11 09:07: `codex exec -m gpt-6.1-sol` on `runs/r13/.../board.png` vs `judge/r13/verdicts.jsonl`).
- **What mattered, in order:** (1) review/fix pass on every board (r2/r3: +7–15 pts, killed layout fails); (2) Swedish-convention reference examples (r9: killed Anglo bracket/"bär 1"/"1 l × 10 = 1 dl" on tune — verified on PNGs); (3) thinking medium over low (r6); (4) findings-only instead of always-review (r12: same quality band, median 22→15 s); (5) sharpened staircase factors (r13: killed hg→g ×10 errors). Traps: review at low (r7: 71%) and high (r10: 64%, reviewer rewrites good boards worse) both backfire; the one-line school-context hint (r5) did nothing; our own blanket "×10 per step" example caused hidden weight errors until r13 qualified it.
| r6b | Exact repeat of r6, tune + hidden, to measure run-to-run spread (n=14 → one board = 7 points) | done. **Tune 64% (clarity 4.1, median 22.2 s)** vs r6's 86%: spread is ±20 pts, r6 was partly luck. **Hidden 82% correct, clarity 4.4, median 22.4 s** (same as r3 hidden). Lead verified 2 fail verdicts against PNGs (Anglo bracket + overflow; "bär 1"); both fair. Remaining errors all Swedish conventions/wording, not layout |

## Parked
- deepseek-v4.1-flash, after r2: best quality (r0 79% tune, r0 hidden 80%) but median 37–63 s in r0–r2; thinking minimal/off made it no faster (off: 57 s). Not kicked: may serve a non-live use. Revisit only with a new speed idea.

- muse-spark-1.3-contributor, after r5: best 64% tune (r4) but only with a review pass at 28–31 s; one-shot 29–36% at 11–21 s. No path to 15 s at useful quality.

## Kicks
- **minimax-m3.1-flash: kicked 2026-11-10 after r4 (lead).** Tune correct 43/43/64/43/43% over r0–r4: no gain in the last 3 rounds, and with any fix or review pass its median is 28–37 s.
- **longcat-2.5-free: kicked 2026-11-10 (Johan: not stable enough).** Ignores `--thinking` (off/minimal still reason >120 s with no HTML); 18/25 r0 boards timed out at 180 s. Its r0 boards stay in the data for reference; it runs in no further round.

## How to run things (lead handbook)
- Every long job: `gym/bin/job <name> "<commands>"` → user systemd unit `gym-<name>`, log `~/gym-data/board-gym/logs/<name>.log`, ends with `JOB-DONE`. It passes PATH (codex/agy need it). `systemctl --user reset-failed` before reusing a name. Never sleep/poll loops; wait on the unit's PID (`tail --pid=$(systemctl --user show -p MainPID --value gym-<name>) -f /dev/null`) as a background command.
- A round: write `gym/configs/rN.yaml` (copy the latest; set `notes:` — the page shows it), then
  `gym/bin/job rN "python3 gym/run.py --config gym/configs/rN.yaml --panel tune && python3 gym/judge.py --round rN --judge argon --batch 2 --parallel 4 && python3 gym/report.py"`.
- Config keys: `prompt` (dir or {member: dir}), `thinking` (level or {member/default}), `review_thinking`, `fix_pass` (false | true = only on layout findings | "always" = review every board), `review_style` (plain | checks), `toolkit`, `members`, `panels`.
- Hidden panel only for checkpoints of a candidate config (`--panel hidden`, same round id). Never tune on it.
- Lead checks 2–3 verdicts per round against the PNGs (`~/gym-data/board-gym/runs/<round>/<member>/<case>/board.png`, verdicts in `judge/<round>/verdicts.jsonl`).
- Page refreshes every 2 min (`gym-board-report.timer`). Per-round grids: `/round-rN.html`.
- Privacy: repo is PUBLIC. Never commit anything from `~/gym-data` (transcripts, boards, judge notes, names). Only code, prompts, configs, aggregate scores.

## Open questions / next (handover 2026-11-10)
- **r6b running** (unit `gym-r6b`, started ~17:30): exact repeat of r6 on tune + hidden. Read its result first: does Haiku medium + always-review hold ~86% tune and how does it do hidden? That is the current best candidate.
- Haiku's remaining errors are Swedish school conventions/wording, not layout: American long-division bracket, "bär 1" for carry (Swedish: "1 i minne"), "deci betyder tio" (tiondel), unit-stair arrows reading "1 l × 10 = 1 dl", "Ett deciliter". The one-line school-context hint (r5) did not help.
- Next ideas, one variable per round, Haiku only, tune panel: (a) short reference examples of Swedish conventions (a correct uppställning for division/addition with "minnessiffra", a unit staircase with unit names, not quantities, on the steps) — conventions as information, not a teaching method; (b) review pass at thinking high; (c) best-of-2 first boards; (d) homework images once the tutor's debug trail stores them.
- Speed: median ~20 s is acceptable (Johan). ~3 s per board is our cold Playwright render; production with a warm browser ≈1 s. Production idea not yet tested: show the first board, swap in the reviewed one if it changed.
- Deliverable at the end: winning Haiku config with evidence (tune + hidden scores, timing), and a production recommendation. Sol (Codex) is back 2026-11-11 09:07 for an independent check of the final hidden verdicts.
- Production note: BoardKit lives only in the gym (fake jsdelivr URL); publishing it needs Johan's OK. Not used by the winner so far.
