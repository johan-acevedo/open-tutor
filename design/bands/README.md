# Age bands: assets and theme tokens

One codebase, three bands (decided 2026-11-18). The request host picks the
band and the band decides the look; it never switches mid-session or on
later visits.

| Band | Hosts | Learners | Status |
|---|---|---|---|
| 1 · primary | `tutor.*` | åk 1–6 (today's fox and style) | live |
| 2 · middle | `tutor2.*` | åk 7–9 (högstadiet) | placeholder: fox + distinct theme |
| 3 · upper | `tutor3.*` | gymnasiet + adults | placeholder: fox + distinct theme |

Unknown hosts (localhost, tailnet dev URLs) default to primary (band 1, åk 1–6).
Testing override: `?band=primary|middle|upper` (also `?band=1|2|3`), remembered
for the next visit, or the server env `TUTOR_BAND` (advertised via
`/api/config`, applies only when the page names no band).

## Where things go

Put finished art under `design/bands/<band>/` (e.g. `design/bands/high/`,
`design/bands/adult/`), then wire it in:

- **Companion art** (web app): `web/src/bands.ts`, per-band
  `companion.greetingImage` (today: `/character/greeting.webp` for all three;
  `companion.asset` is `'fox-placeholder'` for bands 2–3). Band 1 keeps the fox.
  The landing page renders `bandConfig(band).companion.greetingImage`.
- **Web theme tokens**: `web/src/bands.ts` `theme` (accentFrom/accentTo/surface)
  plus the matching `[data-band='middle']` / `[data-band='upper']` overrides in
  `web/src/styles.css`. Keep token names identical across bands.
- **Screen shell theme**: same token names, applied in `screen/shell/` (see
  `screen/README.md`). The screen already knows the band: it travels in the
  session metadata (`learner.band`) and the screen's learner line carries the
  band default (see `server/open_tutor/screen.py` `_learner_line`).
- **Copy**: `web/src/bands.ts` `copy` (Swedish; the upper band says "Byt person" /
  "Ny person" since it covers gymnasiet students and adults, the school bands
  say "Byt elev" / "Ny elev").
- **Tutor register**: `server/open_tutor/prompt.py` `BAND_REGISTER_HINT` +
  `learner_context` (unknown grade defaults per band; adults are never asked
  for a school year). Same voice on all bands for now.

## Screenshots

`design/bands/screens-2026-11-18/` holds the first pass: all three bands at
phone and desktop sizes (first visit → name → call screen; second visit;
Byt elev). Placeholders, not the final look.
