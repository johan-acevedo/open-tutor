# Successive patches: preview the page the child sees

The real session report showed ids missing in the third job. Inspection found those
ids in the preceding patch: the model received them correctly, but each server preview
started again from the original page. This folder contains only a synthetic reproduction,
not the family's page, conversation or ask.

`screen/tools/check_patch_history.py` injects four scripted model replies into the real
Screen job loop and Chromium renderer. First a page; then a patch inserts two ids; the
next replaces one and removes the other and the answer box. A fourth patch has one valid
operation and one missing target. The fourth must never reach the child callback or the
visible history; the tutor gets a failure message instead. No model or Commons calls.

Before the fix, the two missing-id reports reproduce on the valid second patch, and the
bad fourth patch reaches delivery. `browser-before.txt` and `page-370x610-before.png`
capture that failure. The rejection unit cases fail before the fix too (`unit-before.txt`).
After the fix, both valid patches have no issues at 370×610 and 1000×700, the invalid patch
is rejected, and only the two valid changes remain in history (`results.json`). I inspected
both committed patched PNGs. The renderer replays distinct patch batches so a completed
removal cannot become an accidental target in a later batch. Each RPC contains only the
latest patch.

Static previews use reduced motion and finish finite Web Animations before capture. This
removes the fixed one-second post-patch pause and stale highlight boxes; it is a mechanical
latency saving, not a new model-speed measurement. Child-side animations keep their usual
behavior. No look pass or corrective model call is added. Genuine patch errors save
`delivered: false` and use the existing failure callback so the fox can explain or ask again.

```sh
uv run --project server python screen/tools/check_patch_history.py --out /tmp/patch-history
uv run --project server pytest server/tests/test_screen.py -q
```

The source page and patch bodies are constants in the script. It needs Chromium and the
usual shell libraries from the CDN; it is a manual render check, not a network-dependent
CI test. Server tests use injected render/model callbacks and need no key or network.
