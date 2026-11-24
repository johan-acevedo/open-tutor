# UI SDK experiment blocks (append to the prompt, do not merge into REFERENCE.md)

Experiment only, 2026-11-24. The live prompt (screen/REFERENCE.md) is unchanged;
a runner appends this section when it wants the four blocks below. The teaching
frame must be composed with the experiment bundle or the blocks fall back to
native controls with the same messages:

- Python: `screenkit.compose(body, ui_sdk=True)`
- Web: `composePage(body, band, locale)` inlines it automatically wherever one
  of the four tags is present (`hasSdkBlocks` / `uiSdk: 'auto'`).

The blocks use the same sandbox, sanitizer and CSP as every other page: model
markup is plain `ot-*` tags with ordinary buttons and spans, never `ui-*` tags,
never JavaScript. `<script>`, `<style>`, event handlers and `style=` are removed
exactly like elsewhere, in both the native and the DOMPurify fallback path.

Shared rules for all four blocks:

- Every block needs an `id` the tutor can point at. Labels are Swedish prose
  for the child; `value`/`prompt`/`choice` attributes are short keys or words
  the tutor reads back in the answer payload.
- Answers travel to the tutor as `{ot:'answer', id, value}` and drafts as
  `{ot:'input', id, value}`; drafts survive patches and restore like other
  inputs. The submitted `value` is meaningful to the Swedish tutor.
- Never grade in the block: no `correct` attributes, no right/wrong feedback,
  no revealing of answers. The tutor judges the payload in conversation.
- Keep each block small (at most ~6 options/rows) so it fits a 370×610 pane.

## ot-order: put items in sequence

Move buttons are native; each move is announced politely via a `role=status`
live region. Reordering updates the draft; Skicka posts the order.

```html
<ot-order id="ordning" label="Lägg händelserna i rätt ordning, äldst först">
  <span value="gustav">Gustav Vasa blir kung</span>
  <span value="vasa">Vasaskeppet sjunker</span>
  <span value="stormakt">Stormaktstiden börjar</span>
</ot-order>
```

- Children are `<span value="key">text</span>`, shown order first.
- Posted `value` is the keys in current order joined by `>`, e.g.
  `vasa>gustav>stormakt`. The tutor sees the key→text mapping in the page
  source above, so keys must be meaningful words, not numbers.

## ot-match: pair prompts with choices

Each prompt gets a choice control (an SDK select where the bundle is present,
a native select otherwise). Only a completed mapping can be sent: Skicka stays
disabled until every prompt has a choice.

```html
<ot-match id="djur" label="Para ihop djuret med rätt ord">
  <span prompt="hund">Hund</span>
  <span prompt="katt">Katt</span>
  <span choice="dog">dog</span>
  <span choice="cat">cat</span>
</ot-match>
```

- `<span prompt="key">text</span>` rows pair against `<span choice="key">text</span>`
  options; every row offers every choice, in written order.
- Posted `value` maps each prompt to its choice, e.g. `hund=dog;katt=cat`.
- The same choice may be picked twice; the block does not judge, it only
  reports the complete mapping.

## ot-sdk-choice: one radio choice, explicit submit

SDK radio group where the bundle is present, native radios otherwise. Choosing
updates the draft; only Skicka sends.

```html
<ot-sdk-choice id="val2" label="Vilken stad är Sveriges huvudstad?">
  <button value="gbg">Göteborg</button>
  <button value="sthlm">Stockholm</button>
  <button value="malmo">Malmö</button>
</ot-sdk-choice>
```

- Children are `<button value="key">text</button>`, exactly like `ot-choice`
  but with no `correct` marker and no send-on-click.
- Posted `value` is the chosen key, e.g. `sthlm`.

## ot-sdk-answer: short text field, explicit submit

SDK text field where the bundle is present, native input otherwise. Same
attributes as `ot-answer` (`label`, `unit`, `placeholder`, `kind="text"`,
`wide`); Enter sends.

```html
<ot-sdk-answer id="svar2" label="1 kg äpplen kostar 25 kr. Vad kostar 3 kg?" unit="kr"></ot-sdk-answer>
<ot-sdk-answer id="ord" kind="text" label="Skriv ordet på svenska"></ot-sdk-answer>
```

- Posted `value` is the child's text as written.
