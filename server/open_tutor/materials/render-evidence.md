# Step 3a evidence: original-section render packages (elitebook, 2026-11-12)

Module `server/open_tutor/materials/render.py` (stdlib only) plus CLI
`server/scripts/export_material_section.py` and tests
`server/tests/test_materials_render.py`. Rendering only: no HTTP endpoints,
frontend changes, voice tools, search changes, DB, services, or deployment.
`docs/material-library/STATE.md` is untouched; the parent owns serving and
live browser proof.

## What a section package is

- The resolver loads the catalogue once (`SectionResolver`) and resolves the
  exact pinned book version per section ID (SHA-256 re-verified on every
  render). Unknown IDs raise `KeyError`; nothing is guessed.
- The slice is the section's innermost `div.section` scope from the original
  document: balanced by construction, descendants included, the next
  peer/ancestor excluded. Verified structurally across all eight books: every
  nav target has such a scope, and no image reference escapes its document
  directory. Passage `html`/`block_range` spans are never used for display.
- Original tags, attributes, and relative image/CSS references are preserved
  verbatim; stylesheet links are re-emitted in catalogue order. Only the
  package wrapper is new (`index.html` head, provenance header, responsive
  image safeguard), and it adds no `<h1>` so the original heading hierarchy
  is left intact.
- Only members already present in the pinned EPUB are copied (book member
  allowlist); external, absolute, escaping, and missing references are kept
  verbatim in the markup, marked unresolved in metadata, and never fetched.
  Every grades-10–12 content document carries a MathJax `<script>` loader in
  its head: script elements, event-handler attributes, and `javascript:` URLs
  are stripped from slices, so packages are inert and safe to embed later
  with `<iframe sandbox>`.
- `metadata.json` carries title/book/section/source/license (embedded license
  evidence from the download receipts), the exact included descendants, the
  owned-source text summary plus image references for later tutor feedback,
  per-resource resolution, sanitizer notes, and a file manifest with SHA-256.

## Real exports (outside Git, `/tmp/material-exports/`)

```
cd server
bin/with-env uv run python scripts/export_material_section.py \
  --id sec-ecd16baf9e4fee44 --out /tmp/material-exports/grade6-simple-circuit
bin/with-env uv run python scripts/export_material_section.py \
  --id sec-6a9c825e9c3f2cd2 --out /tmp/material-exports/grade10-substitution
```

| section | slice | resources | validation |
|---|---|---|---|
| Grade 6 `A simple circuit` (`sec-ecd16baf9e4fee44`) | circuit illustration kept (20 `images/ec-gd-*` photos/diagrams, incl. the paperclip-switch activity), child `Circuit components` included as descendant, next peer `Circuit diagrams` excluded | 20 images + `custom.css`, all resolved, no warnings | `validate_package` clean |
| Grade 10 `Solving by substitution` (`sec-6a9c825e9c3f2cd2`) | `Worked example 6` kept, next peer `Solving by elimination` excluded | 29 equation-image references (14 unique PNGs; variable glyphs repeat across steps) + `css/stylesheet.css`, all resolved, no warnings | `validate_package` clean |

Both sections report `text_complete: false` (math lives in alt-less PNGs) and
non-empty `license_evidence`. Re-exporting to a second directory is
byte-identical (`diff -r` clean), including `metadata.json`.

## Modern web guidance applied

Retrieved `security`, `html`, and `accessibility` guides before writing the
HTML/CSS logic; `performance`/`responsive-design` were checked but added
nothing beyond the image safeguard below.

- **`html`**: package page uses `<!DOCTYPE html>`, `<html lang="en">`,
  `<meta charset>`, viewport `"width=device-width, initial-scale=1.0"`, a
  real `<title>`, and semantic `header`/`main` landmarks instead of generic
  divs ("DO use the standard HTML5 doctype"; "DO set the `lang` attribute on
  the `<html>` element"; "DO use semantic landmarks").
- **`security`**: the slice ships with no scripts, no external fetches, no
  `on*` handlers, and no `javascript:` URLs, and the page carries an
  embed-with-sandbox comment, keeping untrusted markup out of dangerous
  sinks ("DO NOT: Use `innerHTML` or `setHTMLUnsafe` with untrusted or
  unsanitized input").
- **`accessibility`**: original `alt` text is preserved verbatim (empty stays
  empty; no invented descriptions for the 29 equation images), and the gap is
  recorded honestly via `text_complete: false` plus the owned-text summary
  ("Do apply `alt=\"\"` to decorative visuals" — applied as preserve-don't-
  invent for informative math images the exporter cannot describe).
