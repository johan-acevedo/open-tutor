# Step 3b evidence: read-only HTTP serving of original sections (2026-11-12)

Module `server/open_tutor/materials/serving.py`, minimal wiring in
`server/open_tutor/web.py` (`create_app` gains an optional injected store and
includes the router before the SPA catch-all), tests
`server/tests/test_materials_serving.py`. Serving only: no search/evaluation
change, no frontend/React/client JS, no voice tools, no other board work, no
deploy service, no Tailscale config, no new database, no model loading.
`docs/material-library/STATE.md` is untouched; the parent owns persistent
serving, browser layout proof, and the later voice/frontend integration.

## Routes

| Route | Answer |
|---|---|
| `GET /api/materials/sections/{id}` | JSON for the tutor: `visible_text`, `visible_image_count`, `completeness`, `images` (with URLs), `stylesheets`, `book`, `source`, `license`, `attribution`, `breadcrumbs`, `descendants`, `display_url` |
| `GET /materials/sections/{id}/index.html` | the exported original page, verbatim bytes from the package |
| `GET /materials/sections/{id}/{asset}` | only files listed in the package manifest, with an extension-allowlisted media type (`.css`, `.png`, `.jpg/.jpeg`, `.gif`, `.webp`) |

Section IDs must match `^sec-[0-9a-f]{16}$`; anything else is a 404 without a
lookup, and a well-formed unknown ID is a 404 from the catalogue. A machine
without the pinned EPUBs answers 503 `"Material corpus unavailable on this
host: …"`. A section that cannot be packaged (unresolved resource, unsupported
fetch vector — step 3a refuses these) answers 500 with the reason. `HEAD` is
not routed; every route is GET-only.

## Metadata contract

`owned_text` is *not* served. It is archival provenance covering only the
selected section, while the page also shows descendants, so it is never
presented as visible content. Feedback fields are the rendered scope's
`visible_text` / `visible_image_count` (hidden teacher-guide and grades 4–6
solution subtrees excluded, upper-grade exercises titles excluded), plus
`completeness.text_complete` which follows visible images. `images[].resolved`
is always true for a served package: unresolved references fail the export.

## Package store

- One `SectionResolver` per process, created on first material request
  (lazy), so the eight EPUBs are enumerated once, never per request. Importing
  `open_tutor.web` and all non-material routes work with no corpus and no torch.
- Each section is rendered once per process into a package that stays cached in
  memory (parsed metadata, manifest allowlist, inline-style hashes).
- Disk cache: `$XDG_CACHE_HOME/open-tutor/material-packages` (override with
  `TUTOR_MATERIAL_CACHE`), outside Git. Directory name carries the package
  schema and `PACKAGE_VERSION`, so an exporter upgrade cannot reuse an old
  package.
- Build: `tempfile.mkdtemp` inside the cache root (mode 0700), `export_package`,
  `validate_package`, `.complete` marker with the version, then one `rename()`
  into the final name. A half-written package therefore never becomes visible,
  and a hit without a matching marker or with unreadable/inconsistent metadata
  is rebuilt rather than served.
- Concurrency: a per-section-ID `threading.Lock` serialises generation of the
  same ID (four parallel requests → one export, verified), while different IDs
  build in parallel. Builds run in a worker thread (`run_in_threadpool`), never
  on the event loop.

## Headers and the later sandbox

Every material response: `Content-Security-Policy`, `X-Content-Type-Options:
nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy:
cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=(),
payment=(), usb=()`. The page:

```
default-src 'none'; script-src 'none';
style-src 'self' http://HOST https://HOST 'sha256-…';
img-src 'self' http://HOST https://HOST;
base-uri 'none'; object-src 'none'; form-action 'none'; frame-ancestors 'self'
```

- No `script-src` token at all (not even an empty allowlist), no `unsafe-inline`,
  no bare scheme source, no `data:`.
- The wrapper's inline `<style>` (step 3a) is allowed by its exact SHA-256 hash;
  packaged CSS comes from the response host. The step-3a slice is unchanged.
- `HOST` is the response `Host` header, echoed only when it matches a
  host/port/IPv6 pattern. Both schemes are listed so a proxy that makes the
  internal scheme differ from the public one still matches.

### Checked with real Chromium, not assumed

A same-origin harness page framed both real sections twice, `sandbox=""`
(opaque origin) and `sandbox="allow-same-origin"`, through Playwright:

- Opaque-origin frame: all 20 Grade 6 images and all 29 Grade 10 equation
  images loaded (`naturalWidth > 0`), the packaged `custom.css` /
  `stylesheet.css` applied (`body` computed font from source CSS), the wrapper
  inline style applied via its hash, zero CSP violations.
- `CORP: same-origin` was wrong here and was found this way: inside a
  sandboxed frame the page's own CSS and images were blocked
  (`net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin`, 41 console errors). The
  material responses are now `Cross-Origin-Resource-Policy: cross-origin`,
  which is intentional for CC-BY teaching content and required for the
  opaque-origin embed; after the change the run showed no violations.
- Chromium also matches `'self'` inside a sandboxed frame, but that is not
  relied on: the explicit `scheme://host` source keeps the page working if
  another engine treats the sandboxed origin as opaque for source matching.
- `frame-ancestors 'self'` passes for a same-origin parent page only; a
  cross-origin embed is refused, as intended.

Still open for the parent: the actual `<iframe sandbox="">` (no tokens) in the
React app, the layout/heading-counter proof in a real browser, and whether
surviving inline `style=` attributes in source markup matter visually (CSP
blocks them today; step 3a's sanitizer only rejects fetching ones).

## Real HTTP check (temporary local server, cleaned up)

`TUTOR_MATERIAL_CACHE=/tmp/material-http-cache uvicorn open_tutor.web:app
--port 8791`, backgrounded with a log and an `/api/health` readiness probe,
then `curl`:

- `GET /api/materials/sections/sec-ecd16baf9e4fee44` → 200, `visible_text`
  starts with the section intro, 20 images all `resolved: true`, no
  `owned_text` key, `text_complete: false`, attribution
  `Siyavula — Natural Sciences and Technology, Grade 6 — A simple circuit — …`.
- `GET …/index.html` → 200 `text/html; charset=utf-8`, CSP as above, page bytes
  byte-identical to the package `index.html`; contains the hidden teacher
  prose in markup while the JSON `visible_text` does not.
- `GET …/custom.css` → 200 `text/css; charset=utf-8`; `…/images/ec-gd-0001.jpg`
  → 200 `image/jpeg` (verified JPEG bytes).
- 404s: `…/metadata.json` (not in the allowlist), `…/../metadata.json`
  (resolved by the server to a non-route), `%2e%2e%2f%2e%2e%2fetc%2fpasswd`,
  unknown and malformed IDs.
- Cache after two sections: 132 KB + 1.4 MB, both holding
  `index.html`, `metadata.json`, `.complete`, and only packaged assets.

## Tests

`server/tests/test_materials_serving.py`, 18 tests: metadata contract
(descendants visible, hidden teacher text absent, no `owned_text`), CSP/nosniff/
CORP headers and the inline-style hash, `text/css` + `image/png` +
`image/jpeg` media types, seven asset-traversal/allowlist refusals, unknown and
malformed IDs, missing-corpus 503 with a still-working default app, unpackageable
section 500, one export under four concurrent requests, rebuild of incomplete or
corrupt cache entries, cache outside the checkout, and three real-corpus tests
(Grade 6 circuit, Grade 10 substitution with 29 equation images, the Grade 10
parent section with >100 visible images and `text_complete: false`).

Full default suite after the change: **219 passed, 1 skipped** (was 201 + 1
skipped); no model, network, or browser dependency in the suite.
