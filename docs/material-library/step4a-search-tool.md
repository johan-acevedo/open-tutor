# Tutor material search tool (step 4a)

The first voice-side use of the real local index: one agent tool, `search_materials`, backed by
the saved EmbeddingGemma 2 index from steps 2b/2c. It searches and returns **candidates only**.
Nothing is displayed, no material becomes visible to the child, and a later task owns selecting one
candidate and showing that original section. No HTTP endpoint, frontend change, database, service,
translation, image/audio indexing, corpus build or automatic download is part of this step.

Deliverable: `server/open_tutor/materials/runtime.py` (process-lazy index/model adapter and section
de-duplication), the `search_materials` tool in `server/open_tutor/agent.py`, four lines of tool
guidance in `server/open_tutor/prompt.py`, and `server/tests/test_materials_runtime.py`.

## Configuration: explicit, with no fallback

`TUTOR_MATERIAL_INDEX` names one directory of a **saved index** (written by
`scripts/search_materials.py build` or `scripts/evaluate_material_search.py build`). It is the only
source of an index for the tool:

- Unset or blank: the tool answers that material search is unavailable and names the variable.
  Nothing is loaded, nothing changes for ordinary tutoring, and no proof index is substituted.
- Directory without `index.json`, unreadable metadata, truncated vectors: the same clear
  unavailable answer.
- Optional ML group not installed (`ImportError` for torch/sentence-transformers) or model weights
  missing: the same clear unavailable answer, with the reason.
- A search or inference failure after a successful load: one line saying the search failed, and
  teaching continues in words. The tool never raises into the voice session.

`uv sync --group ml` installs the optional embeddings group; ordinary `uv sync`, the web service
and the normal test suite never import torch.

## Loading, revision and precision

- The index and the model are loaded **lazily, once per process**, and reused for every search. A
  changed `TUTOR_MATERIAL_INDEX` path loads its own runtime; a failed load is not cached.
- The model requested is the exact revision recorded in the configured index
  (`index.json` → `model_revision`), so cached weights cannot drift from the saved vectors. A
  mismatch would be refused by the existing search guard rather than ranked.
- `EmbeddingGemmaEmbedder` already pins CPU, `torch.float32` and text-only loading
  (`vision_config=None`, `audio_config=None`); the runtime refuses any other dtype.
- Index loading, model loading and inference run in a worker thread (`asyncio.to_thread`), so a
  cold start never blocks the event loop. One lock serialises inference on the shared weights.
  There is no per-learner state in this module: the tool builds a fresh result for each call.

## Result contract

Ranking is exact cosine over the configured index. It is reduced to **distinct sections**
(`MAX_CANDIDATES = 5`): the first (best-scoring) passage of a section becomes that section's
candidate, later passages of the same section are dropped rather than filling the list. Each
candidate carries:

| Field | Meaning |
|---|---|
| `rank`, `score` | Order in this result; the cosine between query and the best passage. Ranking only, **not** a confidence that the section answers the question |
| `section_id` | Catalogue section ID the later display step resolves |
| `passage_id` | The best passage in that section |
| `source_excerpt` | The book's own passage text. It may include teacher prose from the original EPUB; it is source text, **not** text the child can see |
| `title`, `breadcrumbs`, `heading` | Breadcrumb path and innermost heading |
| `book_id`, `grade`, `language`, `source_url`, `license` | Source identity. Grade is the South African source grade |
| `text_complete`, `image_count` | `false`/images present means the flattened text is incomplete, e.g. PNG formulae |

The tool adds a fixed `note` telling the tutor that `source_excerpt` is source text the child cannot
see, that `score` only orders candidates, that nothing was shown, that it must read the excerpts and
use one only when it really supports the question, and that the index covers only part of the
library. The prompt gains the same guidance in four lines: build the query from the conversation,
check relevance, and say plainly when no section helps.

`index` in the result reports the honest coverage (`passages`, `sections`, `books`) of whatever index
is configured.

## Real proof on elitebook with cached weights

Run explicitly against the step 2c evaluation index, through the real tool
(`Tutor.search_materials`) and the real model — no stubs:

```bash
cd server
TUTOR_MATERIAL_INDEX=$HOME/.local/share/open-tutor/materials/retrieval-eval-index \
  uv run --group ml python /tmp/mat_smoke.py
```

Model as loaded: `google/embeddinggemma-2`, requested and resolved revision
`f9972ac22e696a105c482202646979e33e4b5a1e`, `torch.float32`, 768 dimensions, text-only, `cpu`.

**Coverage is a subset, not the library.** This index holds 316 passages in 42 sections from 8
books (Grades 4, 5, 6 Natural Sciences and Technology; Grades 10, 11 Physical Sciences; Grades 10,
11, 12 Mathematics). The full extracted corpus is 7309 passages, so this proof exercises the
retrieval-eval pool only. Whole-library indexing and its deployment remain with the parent thread.

Swedish query `Varför fastnar en ballong i håret när man gnuggar den?`:

| Rank | Section | Title | Score | Complete |
|---|---|---|---|---|
| 1 | `sec-26705b4f1e6d5fc4` | Chapter 16: Electrostatics > 16.4 Quantisation of charge > Polarisation | 0.645101 | yes |
| 2 | `sec-5a622d58c15e4483` | Energy and Energy transfer > Energy from the Sun | 0.613230 | yes |
| 3 | `sec-c67665d8276c25ad` | Chapter 16: Electrostatics > 16.4 Quantisation of charge > Grounding | 0.608482 | yes |
| 4 | `sec-0b836ae1e6a86f92` | Chapter 16: Electrostatics > 16.2 Two kinds of charge > Force between charges | 0.608387 | no (1 image) |
| 5 | `sec-ecd16baf9e4fee44` | Electric circuits > A simple circuit | 0.605976 | yes |

English query `How does a closed circuit make a lamp light up?`:

| Rank | Section | Title | Score | Complete |
|---|---|---|---|---|
| 1 | `sec-ecd16baf9e4fee44` | Electric circuits > A simple circuit | 0.806189 | yes |
| 2 | `sec-d38d432f9e2c0b2d` | Electric circuits > A simple circuit > Circuit components | 0.787106 | no (1 image) |
| 3 | `sec-b5f3f397ab1e96aa` | Electric circuits > Circuit diagrams | 0.754055 | yes |
| 4 | `sec-c67665d8276c25ad` | Chapter 16: Electrostatics > 16.4 Quantisation of charge > Grounding | 0.651090 | yes |
| 5 | `sec-f1feb8ae27b67133` | Chapter 16: Electrostatics > 16.2 Two kinds of charge > Tribo-electric charging | 0.646503 | no (1 image) |

The Swedish result reproduces the step 2c manual check (Polarisation first, then unrelated
material), including the point that made this a candidate list rather than an answer: rank 2 is
off-topic at a score close to rank 1. The tutor has to read the excerpts and may decline. Returned
sections are distinct; the two electrostatics sections that share passages are separate catalogue
sections and each appears once.

## Tests

`server/tests/test_materials_runtime.py` (18 tests, no torch) covers: distinct-section de-duplication
with the best passage kept, the candidate limit, the source/metadata/completeness fields, the exact
revision recorded by the index being the one requested, missing/blank configuration, a missing or
unbuilt index directory, a missing ML group, a non-fp32 encoder, one load per process, a changed
configuration path loading its own runtime, loading and inference running off the event loop, the
bounded index summary, blank queries rejected before loading, and the tool's labelled JSON result,
unavailable answer and failure answer. Full server suite: 242 passed, 1 skipped.

No model weights, indexes or evaluation artifacts are added to Git.

## Deliberately not in this step

- No `show_material` tool: candidates cannot be displayed yet, and the tool says nothing is shown.
- No HTTP search endpoint, frontend change or board behaviour change.
- No whole-library index, no automatic download, no new database or service.
- No translation, image or audio indexing, no abstention threshold and no claim that cosine is
  confidence.
- Feedback about displayed material stays deferred: a later show step must use the reviewed
  `visible_text` of the rendered section, never these source excerpts, as what the child sees.
