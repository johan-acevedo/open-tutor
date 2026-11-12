# Step 1 evidence: source catalogue (elitebook, 2026-11-12)

Module `server/open_tutor/materials/catalogue.py` (stdlib only) plus CLI
`server/scripts/catalogue_materials.py`. EPUB nav is authoritative for section
boundaries; no text is extracted, so math-as-image content is never flattened.

## Full-corpus run

```
cd server && uv run python scripts/catalogue_materials.py enumerate | sha256sum
# 4029dd42bb7dbda370d151f5bb6a26545a62a2a67727895b1b5a9a40e4f8ba1a
```

Two consecutive runs give the identical digest (deterministic reruns).
8 books, 1194 sections, all IDs unique, every nav fragment target found in
its content document:

| book | sections |
|---|---|
| natural-sciences-and-technology-4 | 120 |
| natural-sciences-and-technology-5 | 113 |
| natural-sciences-and-technology-6 | 118 |
| mathematics-10 | 173 |
| physical-sciences-10 | 253 |
| mathematics-11 | 128 |
| physical-sciences-11 | 162 |
| mathematics-12 | 127 |

## Spot checks against the real EPUBs

- Grade 6 `Electric circuits` → `sec-18d8044ce2b17e5a`,
  `OPS/xhtml/Grade-6/ec.xhtml#toc-id-0`, no breadcrumbs.
- Grade 6 `A simple circuit` → `sec-ecd16baf9e4fee44`,
  `OPS/xhtml/Grade-6/ec.xhtml#toc-id-1`, breadcrumbs `["Electric circuits"]`,
  stylesheet `OPS/xhtml/Grade-6/custom.css`.
- Grade 10 maths first entry `1.1 Introduction` →
  `01-algebraic-expressions-00.cnxmlplus.html#toc-id-1`, grade 10.
- License: `CC-BY`, catalogue URL `https://creativecommons.org/licenses/by/3.0/`,
  embedded evidence `http://creativecommons.org/licenses/by/4.0/` (from the
  download receipts).

`get --id sec-ecd16baf9e4fee44` round-trips the `A simple circuit` record.

## Tests

`uv run pytest tests/` — 144 passed, including 9 new behavioural tests in
`server/tests/test_materials_catalogue.py` (synthetic EPUBs for nav
authority/unsafe paths, live-EPUB checks, full-corpus determinism).

## Limits

- Navigation/catalogue and source resolution only. No embeddings, image
  generation, HTTP endpoints, extraction framework, UI, agent integration,
  deployment, or DB (per step-1 scope).
- Section display ranges are not sliced yet: a record points at the original
  document + fragment, and serving the exact section span is step 3's job.
