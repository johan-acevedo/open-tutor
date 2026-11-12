# Step 2a evidence: source passages (elitebook, 2026-11-12)

Module `server/open_tutor/materials/passages.py` (stdlib only) plus CLI
`server/scripts/extract_passages.py`. Extraction only: no embeddings, models,
database, HTTP endpoints, UI, or agent integration. English source text is kept
as published; nothing is translated or rewritten.

## What a passage is

- Section boundaries still come only from the EPUB navigation document and the
  corrected catalogue (`SectionRef`). A nav target bounds an excerpt together
  with document order: a passage belongs to the innermost nav scope that has
  already started where the source block sits. A nested section's text is never
  copied into its parent, and trailing parent content after a child section is
  not stolen by the child.
- Headings that are not nav targets (for example `Worked example 6`) stay prose
  inside their section. They never become sections.
- A passage is a greedy run of whole original blocks from one section: it closes
  at 400 characters of text and takes no block beyond 1200 characters. Blocks
  stay whole, so every excerpt maps onto complete original elements; a single
  long block can exceed 1200 characters.
- Containers keep their own leading inline text as its own block, so a list item
  or problem statement that is not wrapped in `<p>` is neither lost nor
  duplicated in its children.
- Images are attached explicitly: archive member path, `alt` (may be `""`),
  `kind` (`math-inline`, `math-block`, `math` for an equation-directory image
  with no class, `image`), and the block ordinal that carries them.
  `text_complete` is false whenever a passage has images, so flattened prose is
  never offered as a complete worked example.
- Each record keeps the original source location (`document_href`, `fragment`,
  `source_href`, `block_range`) and the exact original XHTML slice `html`
  (verbatim bytes from the book, not a re-serialisation).

Record fields: `id` (`psg-` + 16 hex), `ordinal` within the section,
`section_id`, `book_id`, `book_sha256`, `grade`, `language`, `source_url`,
`license`, `license_url`, `heading`, `breadcrumbs`, `document_href`, `fragment`,
`source_href`, `block_range`, `container`, `text`, `text_complete`, `images`,
`html`.

## Full-corpus run

```
cd server
bin/with-env uv run python scripts/extract_passages.py extract | sha256sum
# 1f66d7ce3200c38b59170fe2b16a01f6cfedea1ce11bf8eae4453e794102ebd8
```

Two consecutive runs give the identical digest (31 MB JSON) for the eight
pinned books, 1194 catalogue sections, 7309 passages, all IDs unique. Extraction
takes about 6 s on elitebook.

| measure | value |
|---|---|
| passages | 7309 |
| sections with at least one passage | 1177 (17 sections are heading-only parents) |
| passages with images | 4628 |
| passages with no text (image-only) | 76 |
| math images attached | 41981 |
| images attached without alt text | 43279 |
| text length: median / max | 455 / 4661 characters |

Per book: natural-sciences-4 752, natural-sciences-5 776, natural-sciences-6
811, mathematics-10 942, mathematics-11 738, mathematics-12 884,
physical-sciences-10 1077, physical-sciences-11 1329.

## Spot checks against the real books

- Grade 6 `Electric circuits` (`sec-18d8044ce2b17e5a`): 3 passages, 216 words,
  only its own key questions and teacher notes. The child prose
  "Many misconceptions develop…" appears only in `A simple circuit`
  (`sec-ecd16baf9e4fee44`, breadcrumbs `["Electric circuits"]`, 22 passages).
- Grade 6 `The process of photosynthesis`: a `<figure>` block keeps its image
  (`OPS/xhtml/Grade-6/images/ll-gd-0001.jpg`, no alt) and its caption text.
- Grade 10 maths `Solving by substitution` (`sec-6a9c825e9c3f2cd2`, breadcrumbs
  `["Chapter 4: Equations and inequalities", "4.4 Solving simultaneous
  equations"]`): 3 passages, 29 equation images, `text_complete` false
  everywhere. `Worked example 6: Simultaneous equations` is prose inside that
  section and is not in the catalogue titles.
- Every `html` field is a verbatim substring of its source document (asserted for
  all Grade 10 maths passages).

## Tests

`uv run pytest tests/` — 159 passed. New behaviour tests in
`server/tests/test_materials_passages.py`: nested-nav ownership and no block
reuse, non-nav heading stays prose, math images without alt attached and marked
incomplete, leading problem text kept once, verbatim original slice and full
provenance, whole-document section, chunk bounds, unsafe image src kept verbatim,
deterministic IDs. Live tests (skipped without the corpus) cover Grade 6
Electric circuits, Grade 10 maths worked examples, verbatim slices for a whole
book, and rerun determinism.

```
cd server
bin/with-env uv run pytest tests/test_materials_passages.py -q
```

## Limits

- Passage ranges are not display ranges. The `html` slice can span intervening
  container markup (for example `</li><li>`) and is not necessarily balanced;
  it is a source reference, and step 3 still serves the original section.
- Block ordinals count every block of the document, including section headings
  that are excluded from prose; `block_range` is therefore not contiguous per
  section.
- 76 passages have no text at all (equation tables, picture sequences). They
  carry images for later visual indexing; a text-only embedding pipeline must
  skip or handle them explicitly.
- Alt text is never merged into `text`; only the source's own prose is embedded.
- Alt text and image capture are plain `<img>` only: SVG `<image>`, `<object>`
  and generated rewrites are out of scope.
- Goldens are English as published. No translation, no curriculum mapping, no
  search evaluation or embedding quality claim yet (that is step 2b).

## Cross-family review corrections

Muse independently verified all counts, ownership, resource resolution, and verbatim slices. It found 368 passages with non-contiguous owned blocks: their HTML span can contain intervening content belonging to other sections. In addition, 5497 source slices are unbalanced. `text` and `images` contain only owned content; `html` is an archival byte-span superset, never standalone display content. Records now include exact owned `blocks` ordinals and `html_is_display_content: false`. Display must resolve the original section through its catalogue reference. The `heading` field now uses the in-document heading where available. These serialization changes supersede the digest above.
