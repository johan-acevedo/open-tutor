# Companion and theme verification

2026-11-18, on dell5500. No public deploy or live-service restart.

The review entry serves the actual `Avatar`, `PageCard`, and `BottomBar` components with fictional content. It exercises the band config, shipped WebP URLs, shared CSS token source, sandboxed teaching frame, answer input, and parent callback. It is not a voice session or a substitute for one.

Run against the isolated development server:

```sh
uv run --project server python scripts/check_band_design.py --url <development-url>
```

[report.json](report.json) records six served views: all three bands at 1366 × 768 and 390 × 844. Every view loaded all seven pose images, showed speech bars only for speaking or pointing, matched the board background to the outer app, and delivered the fictional answer "meter" through the real frame message handler. No page errors or horizontal document overflow were observed.

The screenshots are actual served renders. `upper-phone-strip.png` separately checks the production phone stage's compact companion crop and "Visa Björnen" label. The strip keeps the face visible; tapping it returns to the full companion with gestures.

The exporter validates the 14 transparent PNG/WebP pairs, limits height to 900 px, and encodes WebP at quality 88. It preserves the generated source strips and their pose manifest. Existing fox WebP files have no diff. Primary fixed greetings and assembled instructions were also compared with the PR #78 base and found byte-identical.

Local checks: web suite 127 passed, TypeScript and production build passed, review document checks passed. Companion identity and existing teaching checks passed after adapting the upper-band greeting expectation to Björnen. The final full server result is recorded in the PR.

Not tested: a real voice lesson, lip synchronisation, physical phone microphone permissions, and whether learners prefer the characters in sustained use. A/B/C landing designs remain generated images awaiting Johan's choice.

## Web guidance

- `css`: Existing token names are reused in both namespaces. The guide says, "Check for any existing conventions around naming and levels before inventing your own."
- `design-token-reactivity`: Band selection uses attribute selectors because it is core functionality. The guide says, "For core features, an alternate approach using selectors should be used."
