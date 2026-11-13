# Pane context and bounded repair, 2026-11-13

These unedited DeepSeek V4.1 Flash low outputs came from the real `Screen` model
and renderer with pane callbacks for 370×610 and 1000×700. The synthetic ask was
to demonstrate why 3/4 + 1/8 is 7/8, then give a different problem to practise.
Showing the worked answer is intentional in these two cases.

The narrow request delivered readable text at 17.5 px. The wide request fits
its intended pane, but becomes 13 px when re-rendered on a phone. The screenshot
size in the request therefore matters. Both pages were inspected at both sizes.
`evidence.json` records the original two calls and re-renders. Their timings are
individual observations, not a performance comparison.

```sh
uv run --project server python screen/tools/screenkit.py render screen/review/2026-11-13-pane-retry/narrow.html --sizes 370x610,1000x700 --out /tmp/pane-retry
uv run --project server python -m pytest server/tests/test_screen.py -q
```

Parent review found that the worker bounded correction model calls but left the
following render unbounded. The regression test made a repair render take longer
than the job limit: the old code failed the entire job and discarded its first
page. Both look and retry renders now have a deadline with a delivery margin.
A late or failed render keeps the usable page and records why the repair was
dropped. A retry returning `OK` or a patch also keeps the page.

Remaining lint is delivered and logged. It is not a guarantee of readability or
correct teaching. Patches do not get an extra retry. Answer leakage remains a
model judgement, and a long step note can still escape a card without lint.
