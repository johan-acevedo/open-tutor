# Material search: bounded retrieval evaluation (step 2c)

A small, declared, rerunnable evaluation of section-level text retrieval over real Siyavula
material. It is an **engineering check**, not a general benchmark, not a production-quality
claim, and not evidence for a full-corpus or cross-lingual retrieval rate.

Declared dataset: `server/open_tutor/materials/retrieval-eval-dataset.json`
(sha256 `24a485b486c413479ef61db181dabb0a92083c83d44ce04d2529f1f8fa07d514`). The labels were
fixed before any ranking ran; the build records that digest in the index and query metadata.

## What is declared and measured

- 16 concepts across **8 topic groups**, one group per source book: Grades 4, 5 and 6 Natural
  Sciences and Technology; Grades 10 and 11 Physical Sciences; Grades 10, 11 and 12 Mathematics.
- 16 English **and** 16 Swedish spoken-style questions for those concepts, plus 4 absent-topic
  questions in both languages: **40 queries**.
- 32 declared relevant **sections**. Labels name a book, breadcrumbs and heading; they resolve to
  exactly one section in the candidate pool, and a missing or ambiguous label fails the build.
- **319 chosen passages, 316 indexed** (3 image-only passages had no owned text and were skipped
  by design). Passage vectors are 768-dimensional float32.
- The candidate pool is deliberately bounded and topic-coherent (about eight topics, not the
  7,309 extracted passages), so this measures within-topic ranking on declared labels.

| Topic group | Book | Grade | Indexed passages | Image-incomplete |
|---|---|---:|---:|---:|
| Energy and energy transfer | natural-sciences-and-technology-4 | 4 | 27 | 10 |
| Metals and non-metals | natural-sciences-and-technology-5 | 5 | 42 | 6 |
| Electric circuits | natural-sciences-and-technology-6 | 6 | 47 | 17 |
| Electrostatics | physical-sciences-10 | 10 | 45 | 23 |
| Refraction / Snell / TIR | physical-sciences-11 | 11 | 60 | 40 |
| Trigonometric ratios | mathematics-10 | 10 | 29 | 29 |
| Quadratics / discriminant | mathematics-11 | 11 | 33 | 33 |
| Limits / tangents | mathematics-12 | 12 | 33 | 32 |

Metric: rank **sections**, not passages. Several passages from one section count once whether the
section contributes one passage or ten. `top1` means the first section is a declared relevant
section; `top5` means any of the first five distinct sections is. Duplicate sections in the first
five *passage* results are reported separately (82 for the embedding method across 32 scored
queries), because a passage-level top-5 would otherwise count them more than once.

Both methods rank exactly the same 316 passages:

- **EmbeddingGemma 2**: `google/embeddinggemma-2`, revision
  `f9972ac22e696a105c482202646979e33e4b5a1e`, `torch.float32` on CPU, text encoders only,
  official `task: search result | query:` query prompt and `title: … | text: …` document prompt.
- **Lexical baseline**: stdlib BM25 (`k1=1.2`, `b=0.75`) over the same passage titles and owned
  text. One tokenizer and one English stopword list for both query languages; no stemming,
  dictionary or translation.

Language treatment: the corpus is English; Swedish questions are sent unchanged to the same
multilingual encoder. Lexical overlap is reported instead of being translated:

| Queries (including the 4 absent-topic items) | Items | Zero lexical overlap | Mean matched terms |
|---|---:|---:|---:|
| English | 20 | 1 | 4.6 |
| Swedish | 20 | 6 | 0.8 |

## Results

All 32 concept-language queries were scored; no query failed or was dropped. The numbers below are
one build run and a deterministic report; there is no confidence interval, and with 32 scored
queries one query is 3.1 percentage points.

| Method | top-1 sections | top-5 sections |
|---|---:|---:|
| EmbeddingGemma 2 | **29 / 32 (90.6%)** | **32 / 32 (100%)** |
| Lexical BM25 | 15 / 32 (46.9%) | 21 / 32 (65.6%) |

By language:

| Method | English top-1 | English top-5 | Swedish top-1 | Swedish top-5 |
|---|---:|---:|---:|---:|
| EmbeddingGemma 2 | 14 / 16 | 16 / 16 | 15 / 16 | 16 / 16 |
| Lexical BM25 | 14 / 16 | 16 / 16 | 1 / 16 | 5 / 16 |

By topic group, EmbeddingGemma 2 top-1: calculus 4/4, circuits 6/6, energy 2/2, metals 4/4,
quadratics 4/4, trigonometry 2/2, electrostatics 4/6, refraction 3/4. The two weak groups are
concentrated in two concepts (`like-charges-repel` and `snell-angle`) whose question sits between
adjacent sections in the same chapter.

**Read the top-5 row with care.** 100% is saturated because the pool is eight author-chosen
topics and every question's topic group is in it, so five section slots usually contain the right
topic. It is not a general recall result. The discriminating number here is section-level top-1:
90.6% for the embedding model versus 46.9% for the lexical baseline. The English lexical top-1
(87.5%) shows how much exact technical vocabulary is available; the Swedish lexical top-1 (6.2%)
shows that the lexical baseline has no cross-lingual capability.

### Misses

EmbeddingGemma 2 missed section-level top-1 on 3 of 32 queries, and all three still had a relevant
section in the top five:

| Query | Declared labels | First relevant section rank | Top-1 section |
|---|---|---:|---|
| `like-charges-repel:en` — "Why do two things with the same charge push each other away?" | 16.2 Two kinds of charge; Force between charges | 3 | Unit of charge |
| `like-charges-repel:sv` — "Varför stöter två saker med samma laddning bort varandra?" | same | 3 | Conductors and insulators |
| `snell-angle:en` — "How do you work out the angle when light bends into water?" | 5.6 Snell's Law; Refractive index | 3 | Representing refraction with ray diagrams |

The lexical baseline's English misses are `snell-angle:en` (first relevant section at rank 2) and
`complete-square:en` (rank 3); both still hit the declared labels in the top five. Its 17 top-1
misses and 11 top-5 misses are dominated by Swedish queries with no English term overlap. Every
per-query miss and its top five sections are in the saved report artifact.

### Absent-topic questions

The absent questions have no declared relevant section, so they are excluded from the accuracy
counts. They show what the encoder returns when the material cannot answer the question:

| Query | Embedding top-1 cosine | Embedding top-1 section |
|---|---:|---|
| `absent-mobile-screen:en` | 0.6329 | Circuit components |
| `absent-mobile-screen:sv` | 0.5993 | Grounding |
| `absent-wifi:en` | 0.6502 | Representing refraction with ray diagrams |
| `absent-wifi:sv` | 0.6087 | Representing refraction with ray diagrams |
| `absent-sourdough:en` | 0.5920 | A simple circuit |
| `absent-sourdough:sv` | 0.5952 | Energy from the Sun |
| `absent-vaccine:en` | 0.6022 | Grounding |
| `absent-vaccine:sv` | 0.5799 | Grounding |

Absent-topic top-1 cosine is 0.5799–0.6502 (mean 0.6076). Correct topic top-1 cosine starts at
0.6451. One absent query (0.6502) scores above the lowest correct hit. There is **no abstention
classifier and no established threshold**; a tutor cannot read a top-1 score as "the material
answers this". Lexical absent-topic results are recorded too; with no matching terms they fall
back to corpus order.

### Image-incomplete content

190 of 316 indexed passages (60.1%) are `text_complete: false`; the maths books are almost entirely
image-based formula content. 21 of the 29 embedding top-1 hits point to a section whose best
passage is incomplete, and four concepts (`complete-square`, `discriminant-roots`,
`tangent-equation`, `trig-ratios`) have **only** incomplete text in all their declared relevant
sections. Correct retrieval therefore often returns text that is not a complete worked example.
No image, equation or audio indexing was done here.

## Manual check, then automation

Before the report was automated, one Swedish query was checked by hand against the real index:
`Varför fastnar en ballong i håret när man gnuggar den?` returned, in order: Polarisation
(0.645101, relevant), Energy from the Sun (0.613230, unrelated), another Polarisation passage
(0.609279), Grounding (0.608482), Force between charges (0.608387, relevant). That is a real,
partly noisy result, not a fixture score, and it showed both that the model finds the right
chapter and that score separation alone is weak.

## Reproduction and determinism

Build (one real model run; 180.09 s including model load — **not a benchmark**):

```bash
cd server
uv sync --group ml --python 3.13
bin/with-env uv run --group ml python scripts/evaluate_material_search.py build \
  --revision f9972ac22e696a105c482202646979e33e4b5a1e
```

`--revision` is passed to `snapshot_download`. The actual resolved snapshot directory name is
recorded as `model_revision` in the index and query metadata; a requested 40-character commit that
resolves to a different snapshot is refused, and no short revision is expanded into a guessed
hash. `query` defaults to the revision recorded in the index. Weights and artifacts stay outside
Git at `~/.local/share/open-tutor/materials/retrieval-eval-index` (separate from the 118-passage
step 2b proof index, which is not touched).

Report from saved passage vectors, saved query vectors and saved passage text — no model, no EPUB:

```bash
cd server
bin/with-env uv run --no-sync python scripts/evaluate_material_search.py report \
  --details --json ~/.local/share/open-tutor/materials/retrieval-eval-index/report.json
```

Running that command twice produced byte-identical output (sha256
`130bca7f79428f6ec0bb8d438d292bed0c51030af673a0e2b022f0fe10fb95e0`). The report also performs two
independent ranking passes internally and records `identical: true` with ranking digest
`fc0bcddc82fed2f7db41c27f68e5d922c0560f4ba5752a8ef5f34fd544e8f0f2`. This pins rerun determinism
from saved vectors; it does not claim that a second model build would reproduce every float.

## Scope and candidate-selection limitations

- This is **not** a full-corpus evaluation: 316 passages from 8 author-chosen topic groups,
  not 7,309 extracted passages and not a random sample. Topic coherence inflates top-5.
- Selectors match heading/breadcrumb substrings. Four selectors were capped below their match
  count: Snell 33→20, total internal reflection 22→15, nature of roots 22→20, limits 22→20. Those
  declared sections are only partly represented, so their pool coverage is incomplete by design.
- Labels are one author's judgment and some concepts have several acceptable sections (4 for
  "metal or not", 3 for "balloon" and "limit"), which makes top-1 easier than a single-label task.
- Questions are authored spoken paraphrases, not recordings of real learners. There is no
  Swedish translation, no HTTP endpoint, no UI or voice tool, no image/audio indexing, no database,
  no abstention classifier and no latency claim. Ordinary server tests do not need torch.
- The two weak topics are adjacent-section confusions inside the right chapter, not failures to
  find the topic. Do not grow this task to chase individual misses.

## Empirical next step

The result that should change a decision is the pool's effect, not any single miss. The next
bounded unit should rerun this declared dataset against a deliberately confusable candidate pool
(multiple chapters per topic, more near-duplicate distractors) and keep the same labels; that tests
whether top-1 holds when top-5 has room to fail. In parallel, a small threshold/abstention study is
justified because absent-topic (0.6502 max) and correct-topic (0.6451 min) top-1 scores overlap.
Before maths sections are presented as worked examples, the 190/316 incomplete-text finding needs a
visual/equation-completeness plan. None of those steps belongs to this evaluation.

## Tests

`server/tests/test_materials_evaluation.py` covers dataset shape and refusal of too few concepts,
paired languages, exact label resolution and loud failure on missing/ambiguous labels, section
dedupe and top-1/top-5 scoring, lexical English ranking and honest Swedish zero overlap, saved
query-vector round trip, absent-topic separation, and two identical report passes. The revision
helper and reranking from a saved vector without an embedder are covered in
`server/tests/test_materials_search.py`. Ordinary suite: **187 passed, 1 skipped** (the opt-in
real-model test). The opt-in real-model test also passes in the ML environment.
