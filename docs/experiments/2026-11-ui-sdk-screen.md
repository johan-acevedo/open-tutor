# UI SDK exercise experiment

Does a catalogue of interactive UI SDK Web Components help the Smart Screen model write clearer exercises?

## Setup

The control uses the Smart Screen prompt and shell from Open Tutor `5faa730`, including its existing choice buttons, text fields, and diagrams. The experiment adds [four tags](../../screen/ui-sdk-blocks.md) to the model's reference. Both arms write HTML fragments. The shell builds the controls in the existing sandbox and routes submissions through the existing page-answer message. Three new blocks use the UI SDK Web Components. The ordering block uses native move buttons.

The [UI SDK packages](https://github.com/vercel-labs/ui) are Apache-2.0 and in beta. The prototype pins `@ui-sdk/core` and `@ui-sdk/web` to `0.1.0-beta.17`. I checked the [Web Components reference](https://ui-sdk.dev/web.md), the npm package metadata, and the upstream skill on 2026-11-24.

The [runner](../../screen/tools/bench_ui_sdk.py) uses six fictional Swedish homework requests and one page write per arm. Both arms use Muse Spark 1.3 Contributor on OpenCode Go Responses at minimal reasoning. The runner disables look, lint retry, and provider fallback to hold the request count at twelve. The two arms get the same learner band, words, and 370 × 610 pane. I generated the control pages while the prototype was under construction, followed by the SDK pages. Order, connection reuse, and provider load can affect the recorded times. Jobs run in a standalone `Screen` on dell5500 with no voice or room connection.

First visible and fully visible measure from `Screen.ask` through server-side render and the local viewer's copy of the app's ready gate. The viewer records the first animation frame with frame opacity above zero and the first at full opacity. No LiveKit transport runs between those steps. The browser records actual focus changes and key presses, the accessibility tree, and answer messages from the sandbox. The recorded tree is evidence of browser-exposed semantics.

### Clarity rubric

I scored the screenshots on three criteria, each from 0 to 2, for a maximum of 6. For each criterion, 0 means missing or misleading, 1 means usable with a caveat, and 2 means clear.

1. **Lesson content.** The facts are right, the exercise matches the request, and the page leaves the answer for the learner.
2. **Next action.** The learner can tell where to start, what to do, and how to submit.
3. **Readability.** The phone pane fits the content and keeps the text, labels, and controls legible and easy to follow.

A better catalogue should preserve the clarity of the clock and equation and make ordering and matching easier to complete on the page. I treat timings as measurements of this sample. A production speed claim would require repeated runs of the same tasks.

## Results

The new blocks made four exercises clearer. The clock tied, and the equation regressed. The same model used the intended tag on all six SDK pages.

| Exercise | School year | First visible / full, current | First visible / full, SDK | HTML bytes / lines, current | HTML bytes / lines, SDK | Clarity out of 6, current → SDK | Screenshots |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Analogue clock | 3 | 3.82 / 4.06 s | 8.30 / 8.53 s | 303 / 12 | 350 / 9 | 6 → 6 | [Current][clock-control], [SDK][clock-sdk] |
| Water cycle | 5 | 4.86 / 5.09 s | 2.52 / 2.76 s | 440 / 11 | 539 / 8 | 5 → 6 | [Current][water-control], [SDK][water-sdk] |
| English café phrases | 6 | 5.00 / 5.24 s | 2.19 / 2.43 s | 576 / 16 | 425 / 11 | 3 → 6 | [Current][english-control], [SDK][english-sdk] |
| Swedish democracy | 8 | 2.30 / 2.54 s | 2.23 / 2.46 s | 457 / 13 | 500 / 10 | 5 → 6 | [Current][history-control], [SDK][history-sdk] |
| Equation balance | 9 | 4.71 / 4.95 s | 2.82 / 3.06 s | 366 / 12 | 363 / 9 | 6 → 5 | [Current][algebra-control], [SDK][algebra-sdk] |
| Electrical units | Upper secondary 2 | 2.98 / 3.21 s | 2.22 / 2.45 s | 516 / 11 | 460 / 14 | 5 → 6 | [Current][physics-control], [SDK][physics-sdk] |

All 12 pages rendered and fit the pane. The control had one readability warning for the English page at 15.75 px. The SDK arm had no shell warnings in these six pages. Both arms completed keyboard submissions and sent an answer from the frame on all six pages. The fixture covers actual payloads, draft restore, and both sanitizer paths. [Comparison gallery](../../screen/review/2026-11-ui-sdk/index.html) · [Recorded metrics](../../screen/review/2026-11-ui-sdk/results.json) · [Accessibility trees](../../screen/review/2026-11-ui-sdk/accessibility.txt)

| Exercise | Current keyboard and accessibility tree | SDK keyboard and accessibility tree |
| --- | --- | --- |
| Clock | Named buttons send on activation. Each exposes its pressed state. | A named radio group responds to arrow keys. Skicka sends the selected value. |
| Water cycle | A named textbox takes a transcription of the list. | Move controls name their item. Focus stays with the item, and a polite live region reports its new position. Skicka sends one sequence. |
| Café phrases | A named textbox takes letter-number pairs. The format example gives away a pair. | Each phrase has a named combobox. After the learner chooses each option, Skicka sends all the pairs together. |
| Democracy | The learner types a sequence in one named textbox. | The four events can be rearranged using the keyboard, and the new position appears in the live region. |
| Equation | A named textbox and send button accept the learner's suggestion. | A named textbox and send button accept the learner's suggestion. The placeholder mentions subtraction. |
| Electrical units | Three textboxes are all called `Lucka`. Each answer sends on blur. | Three comboboxes name their quantity. Skicka sends a map of all three choices. |

The clock and balance diagrams have unnamed images in both arms. The equation heading exposes no spoken text in either accessibility tree. The café phrases on the SDK page inherit Swedish in the absence of English language tags. These defects matter even when the answer controls work.

Median first visible was 4.27 s with the current shell and 2.38 s with the SDK arm. Median full visibility was 4.50 s and 2.61 s. Full visibility ranged from 2.54 to 5.24 s with the current shell and from 2.43 to 8.53 s with the SDK arm. Each arm ran once per task. Provider generation took a median 3.55 s and 1.54 s in the two batches, while the server render took 0.37 s and 0.45 s. The clock's SDK call spent 6.42 s waiting for its first text. Provider time dominated the sample. The batch order and the variation leave the latency verdict inconclusive.

The model wrote 2,658 versus 2,637 UTF-8 bytes over the six pages, and 75 versus 61 lines. Both arms wrote zero scripts. The version-pinned experiment bundle added **223,793 bytes raw and 79,656 bytes gzip** to a frame that loads it. The built web app entry chunk grew by **245,670 bytes raw and 84,020 bytes gzip** with the prototype shell and the bundle. The frame only loads the bundle when enabled. The web app entry chunk carries the bundle before the frame decides whether to use it. [Bundle metadata](../../screen/shell/ui-sdk.bundle.meta.json)

## Recommendation

**Try further.** Keep the ordering and matching tags as the next experiment. They let learners manipulate the actual steps and pairs, with less transcription. Defer the SDK dependency while testing those tags in a dev lesson. The prototype already implements ordering with native buttons, and a no-inference replay of all six SDK bodies with the bundle disabled reached the parent frame with the same six keyboard payloads. With this sample, the catalogue and the exercise interaction explain the clarity gain. The SDK's clearest contribution was the ready-made radio and picker behavior, including checked state and keyboard navigation.

The test also exposed an answer leak in each arm. The control café page's format hint gave an actual pair. The SDK equation page's placeholder suggested subtraction. Keep judging generated hints separately from control accessibility and shell lint.

## Reproduce and limits

From the repository root, supply `OPENCODE_GO_API_KEY` through the existing developer configuration. Start with an empty output directory for a new set of paid requests. The runner alternates the starting arm on a fresh run.

```sh
mkdir -p /tmp/ui-sdk-baseline
git archive 5faa730 screen/shell | tar -x -C /tmp/ui-sdk-baseline
uv run --project server python -m screen.tools.bench_ui_sdk /tmp/ui-sdk-run \
	--baseline-shell /tmp/ui-sdk-baseline/screen/shell --reference screen/ui-sdk-blocks.md
uv run --project server python screen/tools/check_ui_sdk.py
python3 -m screen.tools.gallery_ui_sdk /tmp/ui-sdk-run \
	screen/review/2026-11-ui-sdk/review.json /tmp/ui-sdk-gallery
```

The [41-check browser fixture](../../screen/tools/check_ui_sdk.py) ran with the real sandbox, native sanitizer and DOMPurify fallback. The lead review checked that raw SDK tags from model markup stay out of the connected page, list reordering keeps focus, and the matching group has an accessible name. The keyboard and accessibility results apply to Chromium's accessibility tree at one portrait size. The full test run passed 630 Python tests and 212 web tests. Type checking and the web build passed.

The experiment used no real children, lesson recordings, LiveKit rooms, or production services. It did not test a live tutor's response, real screen-reader speech, touch on an actual phone, Safari, a wide pane, or the effect of the production look and lint retries. Clarity was one reviewer's judgement. There was one generation per task and arm.

[clock-control]: ../../screen/review/2026-11-ui-sdk/screenshots/clock-control.png
[clock-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/clock-sdk.png
[water-control]: ../../screen/review/2026-11-ui-sdk/screenshots/water-control.png
[water-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/water-sdk.png
[english-control]: ../../screen/review/2026-11-ui-sdk/screenshots/english-control.png
[english-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/english-sdk.png
[history-control]: ../../screen/review/2026-11-ui-sdk/screenshots/history-control.png
[history-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/history-sdk.png
[algebra-control]: ../../screen/review/2026-11-ui-sdk/screenshots/algebra-control.png
[algebra-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/algebra-sdk.png
[physics-control]: ../../screen/review/2026-11-ui-sdk/screenshots/physics-control.png
[physics-sdk]: ../../screen/review/2026-11-ui-sdk/screenshots/physics-sdk.png
