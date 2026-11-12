# Smart Screen: shell, components and example screens

The screen model writes a page body; `shell/` turns it into a finished page in a sandboxed frame.
Start with `NOTES.md` (choices, what was tried, CSP) and `REFERENCE.md` (what the model reads).

```sh
# render one page (and its patch) at 1366x768 and 390x844
uv run --project server python screen/tools/screenkit.py render screen/examples/linjer.html --patch screen/examples/linjer.patch.html --out /tmp/shots
# print the static prompt the screen model gets
python3 screen/tools/prompt.py | less
# rebuild the gallery (screenshots of every example, test page and small-model page)
uv run --project server python screen/gallery/build.py
# serve it on the tailnet
python3 screen/gallery/serve.py --bind "$(tailscale ip -4)" --port 8790
# the small-model test (needs OPENCODE_GO_API_KEY; on dell5500 via the env wrapper)
OPEN_TUTOR_ENV=~/.config/open-tutor-screen-dev/env server/bin/with-env uv run --project server python screen/smalltest/run.py
```

Embedding: put `compose(body)` (see `tools/screenkit.py`) in `<iframe sandbox="allow-scripts" srcdoc=…>`. Wait for
`{ot:'ready'}` before showing the frame. Send `{ot:'patch', html}`, `{ot:'point', id}`, `{ot:'reveal', id}`,
`{ot:'restore', state}`; receive `{ot:'answer', id, value}` and `{ot:'input', id, value}`. Check
`event.source === iframe.contentWindow`. The protocol is documented at the top of `shell/shell.js`.
