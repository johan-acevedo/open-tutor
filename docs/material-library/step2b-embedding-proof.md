# EmbeddingGemma 2 text search: bounded proof (step 2b)

A standalone proof that the real EmbeddingGemma 2 model loads on the ordinary CPU and returns
usable text embeddings for the extracted source passages. It is **not** a production search
feature: no HTTP endpoint, no UI or voice integration, no database service, no translation, no
image indexing, and no corpus-wide performance work. The parent thread owns later evaluation and
integration, and `STATE.md`.

Deliverable: `server/open_tutor/materials/search.py` (exact cosine index, stdlib only),
`server/scripts/search_materials.py` (CLI: `prove`, `build`, `query`), an optional `ml`
dependency group, and the behaviour tests in `server/tests/test_materials_search.py`.

## Model and configuration

| | |
|---|---|
| Model | `google/embeddinggemma-2` (Apache 2.0, not gated) |
| Resolved revision | `f9972ac22e696a105c482202646979e33e4b5a1e` (HF cache snapshot directory) |
| Precision | `torch.float32` on CPU; float16 is refused before it produces quiet NaN |
| Dimension | 768 (native; no MRL truncation in this proof) |
| Encoders loaded | text only: `config_kwargs={"vision_config": None, "audio_config": None}` |
| Query prompt | `task: search result | query: ` (the model's own `SearchQuery`; the embedder refuses to run if the model registers a different string) |
| Document prompt | `title: {title} | text: {content}`, title = breadcrumb path + innermost heading, e.g. `Electric circuits > A simple circuit > Circuit components` |
| Machine | elitebook (HP EliteBook 840 G8, 8 threads, 22 GB), sentence-transformers 6.3.0, torch 2.15.0+cpu, transformers 5.22.2 |

Per the official model card and `ai.google.dev/gemma/docs/embeddinggemma`, `prompt_name="Document"`
applies `title: none | text: `, so titled passages are formatted manually instead. The checkpoint's
processor also imports `torchvision` even when the vision encoder is disabled (sentence-transformers
builds the full processor); that package is in the `ml` group and no vision or audio encoder is
loaded.

Only **owned passage text** plus heading/breadcrumb context is embedded. Passage `html` and
`block_range` are never model input: the reviewed extraction documents that those slices can contain
bytes of neighbouring sections. Passages with no owned text are skipped and counted; passages whose
content is partly images stay in the index with `text_complete: false`.

## Index and sample

`~/.local/share/open-tutor/materials/embeddinggemma-2-index` (outside Git, honouring
`XDG_DATA_HOME`); weights come from the normal HF cache. 118 passages, 768 float32 each: 362 KB of
vectors plus 232 KB of metadata.

Sample (at most 40 passages per selector, built from the real Grade 6 Natural Sciences and Grade 12
Mathematics EPUBs on elitebook):

```bash
cd server
uv sync --group ml --python 3.13
bin/with-env uv run --no-sync python scripts/search_materials.py build \
  --select "natural-sciences-and-technology-6:photosynthesis:40" \
  --select "natural-sciences-and-technology-6:electric circuits:40" \
  --select "mathematics-12:sequences and series:40"
```

- Selected: 80 passages from Grade 6 Natural Sciences (photosynthesis/plants and electric
  circuits), 38 from Grade 12 Mathematics chapter 1 (arithmetic/geometric sequences) as
  distractors.
- Skipped: 2 passages with no owned text (images only) were not embedded.
- `text_complete: false`: 52 of 118. Every one of those 52 has images, and most of the Grade 12
  mathematics passages lose their formulae because the expressions are PNGs without alt text — a
  hit there must be labelled incomplete, not presented as a whole worked example.

## First proof: one real query and two documents

`scripts/search_materials.py prove` (one run, 16.7 s including the model load; that number is not a
benchmark):

| Pair | Cosine |
|---|---|
| "What causes the northern lights?" ↔ "The northern lights are caused by charged particles from the sun…" | 0.789778 |
| "What causes the northern lights?" ↔ "Bread rises because yeast ferments sugar…" | 0.561393 |

Query vector is unit length, the first components are finite and non-degenerate
(`[0.012494, -0.002780, 0.040191, -0.018256]`). This is the model card's own calibration example,
and the ordering matches it, so the checkpoint's weights and prompts are actually in use.

## Smoke queries on the real English material

`scripts/search_materials.py query --limit 5` against the 118-passage index above. Scores are
cosine; `text_complete` is the passage flag that a later tutor must show as "part of this is an
image". The corpus is English, so the Swedish rows are cross-lingual retrieval, not translated
material.

**`how does a battery make a lamp light up?`**

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.7802 | `psg-a22fdc81c79ca9df` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit > Circuit components |
| 2 | 0.7664 | `psg-7f2539f59caf945e` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit > Circuit components |
| 3 | 0.7497 | `psg-11504a3fd41069b8` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 4 | 0.7461 | `psg-165dc2a95e498cc2` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 5 | 0.7423 | `psg-184686643fa05919` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit > Circuit components |

**`how do plants make food from sunlight?`**

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.8163 | `psg-ed8a961f094ab8db` | `sec-767e456e6b9f3295` | natural-sciences-and-technology-6 | false | Photosynthesis > Plants and food > How does photosynthesis occur? |
| 2 | 0.8123 | `psg-9ec876aab3f68afa` | `sec-74d211ac277ca13d` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food > The process of photosynthesis |
| 3 | 0.8007 | `psg-92274fa19af64bdb` | `sec-74d211ac277ca13d` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food > The process of photosynthesis |
| 4 | 0.7808 | `psg-1b7f5cd362a70d51` | `sec-956ab2ea6be65291` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and air |
| 5 | 0.7800 | `psg-cdbadd4467259c9a` | `sec-35bf916c1fc79341` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food |

**`what happens to the current when the switch is open?`**

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.8003 | `psg-15ee4475762d8cf7` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 2 | 0.7850 | `psg-aae0e990fdc84c08` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 3 | 0.7439 | `psg-e3b693fea2e6fa6b` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | false | Electric circuits > A simple circuit > Circuit components |
| 4 | 0.7200 | `psg-2d97797ea5c53230` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | false | Electric circuits > A simple circuit |
| 5 | 0.7117 | `psg-11504a3fd41069b8` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |

**`what is the nth term of an arithmetic sequence?`** (distractors rank first only for a maths query)

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.8100 | `psg-011b789d86435aa4` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |
| 2 | 0.7981 | `psg-3d0fc02b91969edb` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |
| 3 | 0.7979 | `psg-faf9f8fd7d056f91` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |

**`hur får en lampa ström från ett batteri?`** (Swedish query, English material)

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.7539 | `psg-a22fdc81c79ca9df` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit > Circuit components |
| 2 | 0.7254 | `psg-7f2539f59caf945e` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit > Circuit components |
| 3 | 0.7044 | `psg-15ee4475762d8cf7` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 4 | 0.7031 | `psg-165dc2a95e498cc2` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 5 | 0.7031 | `psg-aae0e990fdc84c08` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |

**`hur tillverkar växter mat med hjälp av solljus?`** (Swedish query, English material)

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.7399 | `psg-cdbadd4467259c9a` | `sec-35bf916c1fc79341` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food |
| 2 | 0.7393 | `psg-9ec876aab3f68afa` | `sec-74d211ac277ca13d` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food > The process of photosynthesis |
| 3 | 0.7357 | `psg-c1e724e2ef9f69b3` | `sec-90024c9e1e99a9e6` | natural-sciences-and-technology-6 | true | Photosynthesis > Food from photosynthesis |
| 4 | 0.7324 | `psg-ed8a961f094ab8db` | `sec-767e456e6b9f3295` | natural-sciences-and-technology-6 | false | Photosynthesis > Plants and food > How does photosynthesis occur? |
| 5 | 0.7319 | `psg-92274fa19af64bdb` | `sec-74d211ac277ca13d` | natural-sciences-and-technology-6 | true | Photosynthesis > Plants and food > The process of photosynthesis |

**`hur räknar man ut det n:te talet i en talföljd?`** (Swedish query, English maths material)

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.6694 | `psg-3d0fc02b91969edb` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |
| 2 | 0.6527 | `psg-417dab55fc05dac6` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |
| 3 | 0.6520 | `psg-b5d17226642b5d94` | `sec-549214a97a39647a` | mathematics-12 | false | Chapter 1: Sequences and series > 1.1 Arithmetic sequences > The general term for an arithmetic sequence |

**`hur fungerar en mobilskärm?`** (nothing off-topic in the corpus; no abstention exists)

| # | score | passage | section | book | text_complete | title |
|---|---|---|---|---|---|---|
| 1 | 0.6367 | `psg-f2a1cddef27f7a24` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 2 | 0.5794 | `psg-aae0e990fdc84c08` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | true | Electric circuits > A simple circuit |
| 3 | 0.5729 | `psg-2d97797ea5c53230` | `sec-ecd16baf9e4fee44` | natural-sciences-and-technology-6 | false | Electric circuits > A simple circuit |
| 4 | 0.5723 | `psg-3145a179e02e8b9d` | `sec-d38d432f9e2c0b2d` | natural-sciences-and-technology-6 | false | Electric circuits > A simple circuit > Circuit components |
| 5 | 0.5696 | `psg-345240aa727282df` | `sec-91e8ab0fa3a2d092` | mathematics-12 | true | Chapter 1: Sequences and series > 1.2 Geometric sequences > Example: A flu epidemic |

## What these numbers do and do not show

- Real retrieval works on real English material for both English and Swedish questions: the same
  correct Grade 6 passages come back with real, finite embeddings and no fixture scores. The
  Swedish queries rank the same passages as their English equivalents, with a lower top score
  (0.70–0.75 versus 0.75–0.82), which is the expected cross-lingual cost.
- This is **not a retrieval-quality evaluation**. There are 118 passages, 8 queries, one model, no
  recall/precision metric and no lexical baseline; the Swedish set is a smoke test, not a graded
  benchmark. The parent thread owns that evaluation on the full corpus.
- EmbeddingGemma 2 cosine scores cluster high: the off-topic Swedish query still returns 0.57–0.64.
  A later tutor needs its own relevance threshold and must not read a top-1 score as a claim that
  the material answers the question.
- Mathematical expressions are images with no alt text, so a maths passage's text is incomplete and
  `text_complete: false` says so. Nothing here indexes images, and no visual or audio encoder was
  evaluated.
- The index is exact brute force over 118 unit vectors in pure Python: fine for this proof, not
  sized or tuned for 7,309 passages or concurrent requests. No latency claim is made; the single
  16.7 s `prove` run includes the model load and is not a benchmark.

## Tests and isolation

`server/tests/test_materials_search.py` pins the behaviour without any model download: what text is
sent (titled owned text, never the HTML slice), skipping of empty passages, `text_complete` and
image metadata on a hit, section IDs, cosine ordering on constructed unit vectors, model-revision
mismatch refusal, float16 refusal, and the save/load round trip of the float32 index. The one
real-model test is opt-in behind `OPEN_TUTOR_ML=1`.

`uv sync` (the ordinary server runtime) installs none of it: torch, sentence-transformers and
transformers are absent from the default environment, and the full suite passes there
(175 passed, 1 skipped — the skipped one is the opt-in model test). The ML group is
`uv sync --group ml`; `server/.venv-ml` is git-ignored when a separate environment is wanted.
