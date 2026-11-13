# Sweden's 21 län, for `ot-map`

`lan-sverige.json` is the region geometry behind `<ot-map regions="län">` and `<ot-region>`.

- **Source**: Natural Earth 10m admin-1 states/provinces, pinned commit
  `ca96624a56bd078437bca8184e78163e5039ad19` of `github.com/nvkelso/natural-earth-vector`
  (the same repository and commit as the countries file the shell loads from jsDelivr).
  Natural Earth is **public domain** (no attribution required; the map credits it anyway).
- **Why here and not from the CDN**: the 10m world admin-1 file is 40 MB and over jsDelivr's
  per-file limit, and the 50m admin-1 file contains only nine countries (not Sweden). So the
  21 features are cut out once and shipped with the shell.
- **How it was made**: `python3 build_lan_sverige.py` downloads the world file, keeps the 21
  features whose `adm0_a3` is `SWE`, simplifies them with mapshaper 0.6.109
  (`-simplify 25% keep-shapes`, topology preserving so neighbouring regions keep identical
  shared borders), and quantises the coordinates to whole 1/1000 degrees (about 110 m).
  Names are written the Swedish way (Natural Earth spells them `Skane`, `Orebro`); the label
  point of each region comes from Natural Earth's `latitude`/`longitude`.
- **Format**: `{note, scale, regions: [{code, name, label: [lon, lat], parts: [[x, y, x, y, …]]}]}`,
  where `code` is the länsbokstav (`AB`, `M`, …, from `iso_3166_2`), `label` is the label point,
  and every coordinate is multiplied by `scale` and rounded to a whole number. `parts` are outer
  rings only: no län has a hole.
- **Size**: about 28 kB (21 regions, 2268 points), which is small enough to inline into every
  page frame. It must not travel in a page body: LiveKit RPC caps a message at about 15 kB.
- **Who inlines it**: `screen/tools/screenkit.py` `compose()` and the web app
  (`web/vite.config.ts` + `web/src/shell.ts`) put it in the frame's
  `<script type="application/json" id="ot-map-data">` slot. The shell reads and caches it.

Re-run `build_lan_sverige.py --simplify 40` if the coastlines ever look too coarse; keep the
file well under 150 kB.
