# Teaching iteration: judgement, not more rules

Status: proposal implemented on branch `teaching-judgement-iteration`, awaiting parent review.
No merge, no deployment. Production stays on `main` (`b24ea26`) on ThinkCentre.

## Agreed intent

Better tutoring judgement through coherent principles, missing local experience, and accurate
instruction layers. Not more prescriptive dos and donts. No long rulebook, no mandatory
Socratic sequence. Most existing principles were already good and are kept: explain directly
or ask when it helps, change approach if confused, child authors own work, quiet presence.

Scope (authorised):

1. Refine/reorganise existing How-you-teach BASE, filling gaps: grounding, learner ownership,
   confusion, honest assessment/praise, capability honesty.
2. New short `LOCAL_EXPERIENCE` section in `prompt.py`: 3 curated deidentified family-level
   observations as background, not recipes. Max 3–5, maintainer-curated. No child names,
   no real quotes, no personal data.
3. Tool mechanics accurate: `show_steps` renders rows of equations, not written arithmetic
   column layout. Existing `show_html`/`show_svg` can produce column layout. No new tools,
   no dedicated long-division renderer, no Excalidraw, no UI changes. Volume not controllable
   by agent; make awareness accurate.
4. Memory compatible: existing browser fields `topic`/`clicked`/`tricky`/`next` unchanged.
   `clicked` optional/empty normal. Independent vs helped work described in existing text.
   No forced success story, no schema/migration. Prior `clicked` is not diagnosed mastery.
5. Language: Swedish default, follow requested practice. Resolve instruction conflicts
   (tool docstrings vs English requested). Swedish UI labels unchanged, greeting naturally
   Swedish before any language ask. No hard-coded return to Swedish mid-English session.
   Bounded: no full multilingual engine.
6. Keep Go Muse Spark 1.3 Contributor, reasoning minimal, provider/temperature unchanged.
   Never OpenRouter. Eleven v4 Turbo Bella Swedish default voice, Soniox/Silero, quiet-work
   runtime, prompt prefixing, session lifecycle/auth/logging unchanged apart from guidance
   language. No audio tuning.
7. One short evidence/state doc (this file). English docs. Parent maintains later.
   No real child transcripts.

## What changed

- `server/open_tutor/prompt.py`: BASE reorganised, same agency, plus:
  Language follows the child; grounding (shared vs introduced examples, clarify only when
  it could change teaching); ownership (explain/show/ask/wait, demonstration allowed,
  do not quietly take over thinking); confusion (reconsider representation/prerequisite/step
  size); honest praise (effort/strategy/self-correction, helped vs independent plainly,
  warm initiative, no hesitant interrogator); capabilities (no volume tool, column layout
  possible via html/svg); memory (`clicked` optional, no forced story, prior `clicked`
  not mastery); `LOCAL_EXPERIENCE` with 3 vignettes (answer-giveaway repair, ladder
  helped-but-answer-visible, requested-method replaced and confused), each with context,
  outcome and remaining uncertainty, no new must-do rule.
- `server/open_tutor/agent.py`: tool docstrings only. `show_steps` states rows-not-columns
  and points to html/svg for column methods. Heading language follows speech (Swedish
  unless practising another language). `show_svg`/`show_html` note they can lay out column
  methods. No behaviour change.
- `server/open_tutor/prompt.py` `END_INSTRUCTION`: goodbye in the language spoken
  (Swedish by default), fixing hard-coded Swedish goodbye mid-English session.
- `server/scripts/teaching_probe.py`: new, re-runnable synthetic probes (fictional Leo only).
- `server/tests/test_teaching.py`: new smoke tests for assembly/compatibility only.

What did not change: model route, reasoning, temperature, TTS adapter/voice/language param,
STT, VAD, quiet-work runtime, board protocol/schema, web UI, auth, logging, costs.

## Probes and verification

All probes use fictional material only. No real names, no copied child dialogues, no personal
data. Real Go Muse Spark minimal via ThinkCentre backend env (`bin/with-env`), isolated
`/tmp` copy, production checkout untouched, no worker started, no extra registration.

### Go text/tool probes (new prompt)

`teaching_probe.py --prompt new` (7 cases, 1–2 turns each):

- grounding (only A shared as 4,3×5, asked about B/C): asks to read B/C, invents nothing. Pass.
- objection (synthetic "you gave the answer, I wanted to try"): brief acknowledgement,
  hands turn back, no defence, no interrogation. Pass.
- helped-vs-independent (32 hg→kg ladder, answer already visible, child says 3,2 kg):
  shows steps, praises warmly, asks how they thought. No `save_note` claiming independent
  mastery. Acceptable; remaining uncertainty: praise for a visible answer is generous —
  guidance now says to state helped vs independent plainly and check with a fresh example.
- written (48÷4 uppställning requested): calls `show_html`, not `show_steps`, no
  impossibility claim. Pass. HTML renders readably (see board render below).
- english + english-followup: stays in English across turns, board titles/text in English,
  no unasked Swedish fallback. Pass.
- volume (höj volymen): states cannot change loudness, points to device buttons,
  claims nothing. Pass.
- No caption/tool leaks in any spoken text (`{`, `}`, JSON, tool names absent). Pass.

### Small baseline (old prompt, same config/model)

`--prompt old --cases grounding,written,volume,english` plus extra invention/English-followup:

- grounding, written, volume, english single-turn: same pass as new (asks for missing tasks,
  uses `show_html`, states volume limit, stays in English for one turn).
- invent-no-homework (no tasks shared, "which becomes ~24?"): both old and new ask to
  read/share tasks, invent no numbers. Pass both — the real-session invention failure
  (invented products treated as actual) is not reproduced in single-turn probes.
- eng-followup second turn: both stay in English in these probes.

Baseline reading: single-turn probes do not discriminate old vs new on grounding/written/
volume. The fix is in explicit guidance for the harder multi-turn judgements (grounding
when uncertain, helped vs independent, no unasked fallback) plus the reviewed criteria
below. Passing probes are not learning evidence; real family homework is still the test.

### Merge-blocking review criteria (not runtime gates)

Checked in probe outputs, to be re-checked in family sessions:

- unshared assignment content invented and treated as actual: none in probes.
- false capability claims (volume changed, layout impossible): none; volume correctly
  declined, layout correctly offered via html/svg.
- unsupported independent mastery/memory (visible answer → `clicked` as mastery): none;
  no `save_note` with mastery claim in probes. Remaining risk noted above.
- unrequested language fallback breaking practice: none in probes (English stays English).
- wrong/unreadable written-method board: none; both new and old HTML render readably
  with correct maths (see next).

### Board render (real Chromium, board iframe path)

Model-produced `show_html` for 48÷4 (new and old) rendered in the real board iframe path
(`sandbox="allow-scripts"`, board CSP, `#181B22`/`#F3F5F8`/`#22D3EE`/`#A78BFA`) via local
Chromium headless (`chrome --headless --screenshot`, ordinary browser tooling, no T3 preview):

- new: `48 ÷ 4 = 12`, columns `4 1 / 4 2`, notes "4 i 4 går 1 gång", "4 i 8 går 2 gånger",
  "Kort division: 4→1, 8→2. Svaret blir 12." Readable, maths correct (4→1, 8→2, 12).
  Layout is short-division explanation, not traditional Swedish uppställning, but
  understandable and not wrong.
- old: `4 ) 48` with `12 ← svar`, "4 i 4 går 1 gång → 1", "4 i 8 går 2 gånger → 2",
  "Rest 0". Readable, maths correct.

Headless render is rendering evidence only, not proof a child learns. `show_steps` rows
vs column distinction is now explicit in prompt + docstrings; `Cards.tsx` already renders
rows (unchanged).

### TTS language (no config change)

Official ElevenLabs docs (checked 2026-11-07, `text-to-dialogue/convert` + capabilities):

- `language_code` (ISO 639-1) enforces a language for model + text normalisation; if the
  model does not support it, it is ignored. No documented `auto` value, no autodetection
  flag, no mixed-language mode in the API reference or Text-to-Dialogue overview.
- v4 supports 90+ languages; v4 Turbo is the real-time model. No statement that omitting
  `language_code` auto-detects per sentence.

Decision: keep forced `language="sv"` (`DialogueTTS`, `build_tts`), unchanged. English
practice will be spoken with Swedish-enforced pronunciation; LLM output language and TTS
pronunciation are distinct — do not claim forced TTS `sv` caused an LLM language switch,
and do not claim English voice is fully supported. Limit explicitly reported here rather
than shipping an unverified autodetect change. No Swedish+English TTS audio generated or
listened to for this iteration (no config change to verify).

### Tests

- `uv run pytest -q` (server): 72 passed + new teaching tests (see below) — full suite
  once stable, narrow files while iterating.
- New `test_teaching.py` checks assembly/compatibility only: instructions contain learner,
  Note fields unchanged (`topic`/`clicked`/`tricky`/`next`), END follows spoken language
  (no hard-coded "Swedish sentences"), BASE keeps agency anchors and local-experience
  bounds. No exact-wording mirrors.
- Web untouched: `npm run typecheck`, `npm test`, `npm run build` to be run before PR
  (CI runs them).

## Limits and remaining uncertainty

- Model reliability is judged from short synthetic probes, not a real session. Invention
  under longer context, helped-vs-independent praise calibration, and English persistence
  across interruptions still need family homework to evaluate.
- TTS English quality unverified by design (config unchanged). Swedish default voice,
  identity and route unchanged.
- Volume: awareness only, no control. If asked, tutor declines + points to device.
- Written method: short-division HTML is readable and correct here, but traditional
  uppställning preferences may vary by school/year — family test should confirm the
  offered form helps, not just renders.

## Next step (parent owns)

Review diff + this evidence, merge PR, deploy via normal path. Real family homework still
required as follow-up; passing probes are not learning evidence. If model reliability is
not good in family use, stop and reassess rather than expanding architecture/providers.
Parent maintains this doc if later needed.
