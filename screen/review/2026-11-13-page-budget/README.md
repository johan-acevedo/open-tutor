# Page timing budget, 2026-11-13

The 20 s ceiling is working in the measured jobs. The under-12 s target is not
met on this route. All five later jobs skipped the look and still took
13.6–17.9 s because generation alone took 12.4–16.5 s. No job failed in either
batch. This is not a claim of a controlled speedup: the batches ran sequentially
and first-call latency changed between them.

## Measurements

DeepSeek V4.1 Flash, low reasoning, OpenCode Go endpoint, identical synthetic
fractions ask and conversation, 721×636 pane. dell5500 had 8 CPUs and load
averages around 1.5–2.0. Real provider requests and the real Chromium renderer
were used. Each original look saw its own first-render PNG; all returned `OK`,
not a rewritten page. `before.json` and `after.json` contain every job's stages,
issues, failure count, input/output character counts and image byte counts.

| Job | Model | Render | Look | Total |
|---|---:|---:|---:|---:|
| Before 1 | 17.41 s | 1.41 s | 5.83 s | 24.66 s |
| Before 2 | 9.75 s | 1.24 s | 7.89 s | 18.88 s |
| Before 3 | 8.53 s | 1.19 s | 13.11 s | 22.82 s |
| Before 4 | 14.35 s | 1.26 s | 13.72 s | 29.34 s |
| Before 5 | 10.08 s | 1.24 s | 8.13 s | 19.45 s |
| After 1 | 16.51 s | 1.43 s | skipped | 17.94 s |
| After 2 | 13.07 s | 1.22 s | skipped | 14.29 s |
| After 3 | 12.42 s | 1.20 s | skipped | 13.62 s |
| After 4 | 14.54 s | 1.32 s | skipped | 15.86 s |
| After 5 | 15.17 s | 1.44 s | skipped | 16.61 s |

The old short look prompt was also called once on each identical first draft
and PNG, after its normal job finished. It returned `OK` in all five cases at
4.97, 6.55, 7.57, 6.22 and 5.16 s. It had 385 input characters against about
1,700 for the new look request. The always-second order can favour the control
through caching and provider drift. Rewriting is not the source of the extra
look time in these samples; the exact share due to request wording versus
provider variance remains uncertain.

A separate streaming diagnostic (`profile.json`) received its first text at
10.54 s and finished 484 HTML characters at 12.19 s. Usage reported 510 reasoning
tokens and 6,528 cached prompt tokens out of 6,799. Most of that observation's
wait preceded visible HTML, rather than writing it. It does not separate provider
queue time from thinking. DeepSeek documents a separate
[thinking-mode toggle](https://api-docs.deepseek.com/guides/thinking_mode/);
low effort still uses thinking. Testing disabled thinking is the next hypothesis.

The diagnostic reported `opencode.billing_source: balance` and a nonzero cost.
[OpenCode's inference documentation](https://opencode.ai/docs/console/api/inference/#cost)
defines this as balance billing rather than Go allowance. Further inference
tests were stopped and the lead was informed. No billing setting was changed.

## Policy and quality tradeoff

The first model call leaves two seconds for rendering inside a default 20 s job.
Clean pages get a look only when the 12 s soft target has room for that call and
a final render. Known lint goes straight to one source-and-lint correction.
Each optional model call has a 6 s ceiling, with no look-plus-retry chain.
`SCREEN_LOOK=always` is available for diagnostics inside the hard limit.

This deliberately loses semantic checking on many clean pages. A diagram can
give away an answer without any lint. The reference still prohibits that, but
skipped inspection is logged rather than described as a quality pass. Late or
failed corrections preserve the first usable page. Generation that exhausts
its budget tells the tutor to explain in words.

The saved `page.html` is unedited output from the first later job. Its renders
at 370×610 and 1000×700 were inspected. They fit without lint at 17.5 and 29 px.
This does not prove every generated page is pedagogically sound.

## Repeat

```sh
# Real provider calls; resolve the billing question before running these again.
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env uv run --project server python screen/tools/bench_page_budget.py --out /tmp/page-budget --legacy-look
OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env uv run --project server python screen/tools/bench_page_budget.py --out /tmp/page-profile --profile-only
# No provider calls:
uv run --project server python -m pytest server/tests/test_screen.py -q
uv run --project server python screen/tools/screenkit.py render screen/review/2026-11-13-page-budget/page.html --sizes 370x610,1000x700 --out /tmp/page-budget-shots
```

The soft-budget and independent-call-cap checks both fail against the previous
implementation and pass with this policy. Pure toolbox tests are now included
in the server pytest `testpaths`; live probes remain outside test collection.
