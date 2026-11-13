# Inert page source and sanitized insertion, 2026-11-13

The previous shell executes a model-written inline script. The new page and
patch paths remove it before insertion. Real Chromium checks cover native
`setHTML`, the actual DOMPurify fallback, blocked fallback loading, handlers,
script markup, unsafe URLs, a colour-to-SVG injection, teaching attributes,
patching and reveal. A missing sanitizer keeps the source inert and reports a
boot issue. No raw-HTML fallback exists.

```sh
uv run --project server python screen/tools/check_sanitizer.py
npm test --prefix web
npm run build --prefix web
uv run --project server python screen/tools/probe_local_shell.py --shots-dir /tmp/screen-shell-e2e
```

The existing `server/scripts/smart_screen_e2e.py` completed with 30 events and
zero browser console errors. The wrapper substituted this checkout's built
index and assets only in the probe browser. APIs, voice and page generation
used the existing dev backend. Services and other visitors were unchanged.
The source template is removed during boot. The probe found a real heading,
an answer box and no raw HTML tags, submitted 7/8, received the tutor's correct
answer acknowledgement and reached the end card. The original probe needs no
DOM-selector change. Its “assume patch” event does not prove a patch was sent;
the separate sanitizer check verifies patch insertion and reveal directly.

The two unedited DeepSeek pages from `../2026-11-13-readability/` were rendered
again at 370×610 and 1000×700. All four PNGs are byte-identical to those saved
renders and were inspected again. No new model syntax is introduced.

All 76 web tests and the build pass, plus 180 server tests and the readability
browser checks. `pagecard.test.tsx` now checks inert source before shell boot,
rather than expecting a live heading in the composed source. The composer test
compares body encoding with Python's actual composer.

The largest serialized example `PageItem` is 1,348 UTF-8 bytes, including its
title and ID. The shell and escaping are added after RPC, so the transport
change does not enlarge the message. Safari is not verified on a physical
device. Chromium exercised its library fallback by disabling the native API.
