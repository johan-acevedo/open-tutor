# Board gym

Harness that runs member models on real board moments and judges the boards.
Private session data (cases, prompts with transcripts, boards, PNGs, judge
notes) lives in `~/gym-data/board-gym/` and **never enters git**. Committed:
code, prompt templates, configs, and aggregate numbers in `gym/scores/`
(no quotes from conversations).

## Commands

```bash
# Build cases (pulls new debug trails from thinkcentre)
python3 gym/ingest.py

# Run a round (panels from the config; --panel/--members/--cases narrow it)
python3 gym/run.py --config gym/configs/r0.yaml
python3 gym/run.py --config gym/configs/r0.yaml --panel tune --members muse-spark-1.3-contributor
python3 gym/run.py --config gym/configs/r0.yaml --panel tune \
  --members muse-spark-1.3-contributor --cases OBK5VCNGuYtO-b2,n8F-ELseR-_x-b1
# --force re-runs finished run dirs

# Judge a round (auto alternates judges; Haiku batches always go to both)
python3 gym/judge.py --round r0
python3 gym/judge.py --round r0 --judge opus   # or: sol
python3 gym/judge.py --round r0 --judge auto --force

# Aggregates + progress site
python3 gym/report.py [--round r0]
```

## Layout

- `gym/run.py` — fills `prompts/<p>/system.md|user.md` per case, calls
  `pi -p --model opencode-go/<member> --thinking <thinking> --no-tools
  --no-session --no-context-files --no-skills --no-extensions --mode json`
  with the system prompt + `@prompt-user.md` (+ `@board.png` on fix pass),
  extracts `board.html`, renders `board.png` (1920×1080), lints to `lint.json`.
  At most 4 calls in flight, 1 per member. Timeout 180 s, no retries.
  Run dirs: `~/gym-data/board-gym/runs/<round>/<member>/<case_id>/`;
  records appended to `~/gym-data/board-gym/results.jsonl`.
- `gym/judge.py` — blind judging in batches of 5. Opus reads PNGs via
  `claude … --tools Read --add-dir`; Sol gets `--image` attachments via
  `codex exec`. Rubric: `gym/prompts/judge.md`. Output:
  `~/gym-data/board-gym/judge/<round>/verdicts.jsonl` (+ `key.json`,
  per-judge `raw/`), merged back into `results.jsonl`.
- `gym/report.py` — per round × member × split aggregates (n, % correct,
  mean clarity, median/p90 wall, fails) to `gym/scores/<round>.json`, and
  the private site to `~/gym-data/board-gym/site/`.
- `gym/render/` — Playwright renderer + layout lint (only
  `https://cdn.jsdelivr.net` allowed; optional local toolkit file served at
  a fixed jsdelivr-style URL via `TOOLKIT_URL`/`TOOLKIT_FILE`). Needs
  `npm install` in `gym/render` (playwright-core; Chromium is cached).
- `gym/systemd/gym-board-site.service` — serves the site on
  http://100.91.148.43:8743. Install:
  `cp gym/systemd/gym-board-site.service ~/.config/systemd/user/ &&
  systemctl --user daemon-reload && systemctl --user enable --now gym-board-site`

## Targets (hidden panel)

Median wall ≤ 15 s (incl. any fix pass), ≥ 90% correct, clarity ≥ 4.5/5.

## Privacy

The repo is public. Before every commit, check `git status`: only code,
templates, configs (incl. `notes:`), and aggregate numbers may be committed.
