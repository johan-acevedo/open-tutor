# Readability check, 2026-11-13

Two synthetic requests, DeepSeek V4.1 Flash on OpenCode Go with low reasoning.
The saved HTML and patches are unedited model output. No look pass runs in this
small-model test. Timings in `summary.md` describe these calls only.

```sh
SMALLTEST_OUT=/tmp/readability OPEN_TUTOR_ENV=~/.config/open-tutor-smart-dev/env server/bin/with-env uv run --project server python screen/smalltest/run.py --model deepseek --requests screen/smalltest/readability-requests.json --sizes 370x610,370x558,1000x700
uv run --project server python screen/tools/check_readability.py
```

The author inspected both pages at 370×610 and 1000×700. Fractions fits at
17.5 px on the phone. The line page still needs less content, at 14.75 px.
Both patches add enough content to make the phone pages dense. The new lint
reports these cases. Server correction and delivery policy is a separate change.

The line page gives away the answer in its explanation before asking the same
question. This remains a teaching flaw despite the stronger reference wording.
Lint cannot determine whether an arbitrary diagram reveals the intended answer.

`screen/tests/readability/` contains two earlier unedited model outputs used for
deterministic warning checks. The reading-order check fails against the previous
shell because rows and grids show two columns at 370×300. It passes with this
shell. A 15 px phone page now warns even though it did not meet the previous
14 px warning threshold.
