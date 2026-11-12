# Material library implementation

Lead: this T3 thread. Scope: let the voice tutor search educational material from the conversation, choose an original section, display it beside the avatar, and teach from the visible content. English source material first.

## Delivery steps

1. Source catalogue: stable section IDs, original EPUB locations, headings, source and license records. Muse implements; DeepSeek reviews. No model or UI changes in this step.
2. Search: passage extraction, EmbeddingGemma 2, a lexical baseline, and Swedish query evaluation. DeepSeek implements; Muse reviews. Verify real model output on the downloaded books before integration.
3. Display: serve original sections with their images and styles, resolve IDs, and acknowledge when the material is ready. A bounded worker implements; the other model reviews. Reuse the existing board surface without redesigning the ongoing advanced-board work.
4. Voice integration: explicit search and show tools, candidate choice by the tutor, visible-content feedback, and real end-to-end verification. Review cross-family before merging.

Each step gets a small brief and ends with executable evidence. Workers use isolated worktrees. No translation, accounts, curriculum knowledge graph, vector database service, or general reader UI is required.

## Design constraints

- Search units can be smaller than display units. Every hit resolves to the exact original book version and section.
- EPUB images and styles remain available. Many mathematical expressions are PNGs without alt text, so plain text is not a complete teaching source.
- Grade labels are South African source grades, not Swedish school-year mappings.
- EmbeddingGemma 2 uses SearchQuery/Document task prompts, float32 on ordinary CPUs or supported bfloat16. Do not use float16.
- Load text only for text queries; evaluate selective visual section indexing separately. No audio encoder is needed for transcribed speech.
- Displayed material stays in active teaching mode. The existing resource tool's quiet-video behavior is unsuitable.
- Agent sees candidate content and selects a source ID; it does not invent material URLs. Browser readiness and visible source content must reach the tutor before it refers to them.

## Current state

Steps 1 and 2a are implemented and cross-reviewed. Step 2b has a real-model proof awaiting Muse review. Eight validated EPUBs are on elitebook at ~/.local/share/open-tutor/materials/siyavula, with books.json and validation evidence under tools/siyavula. The served corpus is https://elitebook.tail2e1c4e.ts.net/open-tutor-materials/.

Source baseline: origin/main 675f334. Existing material tools are independent of the tutor. EmbeddingGemma 2 has now run on a bounded 118-passage sample; this is not yet a full-corpus retrieval evaluation or integrated tutor feature.

## Step 1 review

Muse delivered e6676e1. DeepSeek independently reproduced all 1194 references and found stale publisher nav targets and missing span-only chapter breadcrumbs. Parent corrected unique heading matches while preserving raw source_href, added actual heading/mismatch fields, retained stylesheet order, and decoded fragments before IDs are persisted. Remaining label differences stay explicit. Request handlers must load the catalogue once rather than re-enumerate EPUBs on every lookup.

Next bounded unit: step 2a extracts source passages from the corrected section references. Embedding inference is a separate step 2b, followed by real retrieval evaluation. No UI work begins before source extraction and search have evidence.

## Step 2a review

DeepSeek delivered 15c1b2b. Muse independently verified 7309 passages with no missing non-heading blocks or duplicated ownership. Parent added exact owned block ordinals and marked HTML spans as non-display content: spans may include intervening foreign content and unbalanced markup. Search consumes owned text and image references; display resolves catalogue sections, never passage HTML spans. The next unit is a standalone text retrieval proof with real EmbeddingGemma 2, before any endpoints or UI integration.

## Step 2b proof, awaiting review

DeepSeek delivered 6ffdf42: optional CPU ML dependencies, exact local cosine index, and prove/build/query CLI. Real google/embeddinggemma-2 text-only fp32 inference on elitebook returned matching relevant circuit/photosynthesis passages for English and Swedish smoke queries. Index and model weights remain outside Git. See step2b-embedding-proof.md for exact results and revision. No quality metric, off-topic abstention, latency claim, or full-corpus evidence yet. Muse owns independent review, including prompt configuration, revision handling, saved-index integrity, metadata ownership, and reproduction against real cached weights. Parent owns fixes and the subsequent lexical baseline/broader evaluation before HTTP or voice integration.

## Step 2b review

Muse independently reproduced real model scores and returned IDs for both languages. Full default suite: 175 passed, 1 skipped; opt-in real-model tests also passed. No blockers. Parent removed enclosing block_range from search results so a later display consumer cannot confuse it with exact owned source content. Existing on-disk proof index predates this metadata correction and must be rebuilt before serving results. Next bounded unit: revision-pinned broader sample evaluation against a lexical baseline, with declared query relevance and off-topic examples; no HTTP or UI integration yet.

## Step 2c evaluation, awaiting review

DeepSeek delivered 73c1dd3: declared paired-language questions, a 316-passage evaluation pool, BM25 comparison, saved-vector rerunnable report, and explicit model revision support. Muse must verify label appropriateness and scoring against real artifacts before results are accepted. Corpus choices are deliberately bounded; this is not general retrieval quality. Scores for absent topics overlap scores for correct results, so the tutor must inspect candidates rather than treat cosine as answer confidence. Formula-heavy text remains incomplete: display must preserve original images and feed visible material back to the tutor.

After this review and any small fixes, proceed to step 3 original-section rendering. Further confusable-pool evaluation is deferred until the complete prototype can be exercised; do not add a threshold classifier or keep expanding offline benchmarks now. Prototype search returns several distinct section candidates with excerpts/completeness/source metadata; the tutor selects only relevant material or declines when none supports the question. No automatic top-hit display based on score alone.

## Step 2c review complete / step 3a

Muse independently reproduced the saved report and checked labels against original XHTML: no blockers. Parent made future dataset provenance paths repo-relative (custom external datasets use filename plus authoritative SHA-256); existing archived reports retain their original digest. Offline evaluation is frozen. Next step 3a is a source-section render package and rerunnable export CLI, using original markup/images/styles and exact catalogue IDs. HTTP/browser/voice wiring follows in separate bounded units. Section display may intentionally include descendant subsections; it must stop before the next peer/ancestor, retain balanced markup, and never use passage HTML spans. All math formula images must survive rendering.

## Step 3a render package, awaiting review

Muse delivered 2583e06: SectionResolver, balanced original section scope with descendants, export/validation CLI, and real circuit/equation examples. DeepSeek owns independent cross-review before HTTP serving. Parent identified two review questions: unresolved external resource URLs remain in markup (no Python fetch does not imply no browser fetch), and metadata owned_text/text_complete covers only the selected section while its visible slice includes descendants. Check actual corpus impact and retain these distinctions before tutor feedback is wired. Export wrapper currently exposes verbose developer provenance; the eventual child-facing view needs compact attribution and original teaching content, with diagnostic details confined to metadata.

## Step 3a review corrections

DeepSeek reproduced all original images and identified three integration blockers. Parent added visible_text and visible_image_count from the entire rendered scope, excluding the audited Siyavula hidden teacher-guide/grade-4–6 solution subtrees and upper-grade exercises-title selector. owned_text remains archival provenance, never a claim about visible content. text_complete now follows visible images. Export refuses unresolved resources and unsupported automatic-fetch elements/attributes/CSS instead of silently retaining them. Require fresh empty directories to avoid stale assets. Compact attribution replaces developer metadata in the page; diagnostics remain in metadata.json. The original slice is a body child (including body-less frontmatter), retaining source CSS selectors. HTTP must still enforce CSP and sandbox; no general sanitizer claim. Heading counters and actual browser visibility remain to verify in step 3b/3c. Fourteen renderer tests pass including real parent maths feedback and hidden circuit teacher text.

## Step 3b HTTP serving, awaiting review

DeepSeek delivered 391ffd4 + 05a1fdc. Read-only section metadata, original HTML and allowlisted assets are wired into FastAPI; process-lazy resolver and versioned atomic disk package cache live outside Git. Worker verified actual HTTP and Chromium sandbox image loading on elitebook. Cross-Origin-Resource-Policy same-origin broke opaque sandbox resource requests, so public CC-BY material responses deliberately use cross-origin while page framing remains self-only. Wrapper style uses a CSP hash; source inline style attributes currently remain blocked. Full worker suite: 219 passed, 1 skipped. Muse owns independent review of cache/revision, CSP, asset boundaries, browser load evidence and tutor metadata before persistent serving or frontend wiring. No UI or voice integration yet.

## Step 3b review correction / next step 3c

Muse reproduced real HTTP, opaque-sandbox images and metadata with 219 passing tests. One proven multi-process collision deleted a complete package while another process served it. Parent changed publication to adopt the verified winner (also re-check before stale-target removal), added a collision regression check, and documented single-worker prototype deployment. No other blockers. Next step 3c: minimal material board item + sandboxed original-section component and load acknowledgement, preserving the fox and ongoing generated-board feature. Voice tool and real model search integration follow separately.
