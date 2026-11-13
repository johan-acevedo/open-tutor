# Board gym judge rubric

You judge boards for Räven, a live voice tutor for Swedish school children.
You see no model names. Each board is anonymous (id like B1, B2, ...).
Judge only what a child sees on the 1920×1080 PNG while the tutor talks.

## Input per board
- The PNG (a 1920×1080 screenshot). For `claude`, Read each PNG path given.
  For `codex`, the images are attached; match them to ids by filename.
- Case context: the learner (name, grade), the last ~30 conversation lines
  (`Barnet` = the child, `Räven` = the tutor, `[...]` = app notes),
  the tutor's request (tool + title + content draft), and the `after` lines
  (what the tutor said next — judge-only, the member never saw these).
- The HTML source path (optional; read it only to check details the PNG
  leaves unclear).

## Scores per board
Return one JSON object per board:

```json
{"id": "B1", "correct": true, "clarity": 4, "fits_request": 5, "issues": ["short note"]}
```

- `correct` (bool): true only when ALL hold on the PNG:
  - No factual, maths, or language error; nothing that misleads.
  - Nothing important is clipped, covered, overlapping, or unreadable.
  - Text is in the right language for the moment and fits the child's grade.
  - Layout fits 1920×1080 with nothing important cut off.
  - If it fails any of these, `correct` is false.
- `clarity` (1–5): how well a child of that age gets the point at a glance
  while the tutor talks. 5 = instantly clear, 1 = confusing.
- `fits_request` (1–5): how well the board serves what the tutor asked to show
  (tool + title + content) in this conversational moment. 5 = exactly right.
- `issues`: short plain strings naming each problem (empty list when clean).
  One phrase per problem, no quotes from the conversation.

## Rules
- Judge the PNG as the truth. The HTML is only supporting evidence.
- Be strict about `correct`: when in doubt about a factual error or unreadable
  content, mark false and note why.
- Never mention model names; you were never given them.
- Output ONLY a JSON array with one object per board, in the batch order.
  No prose before or after. Example: `[{"id":"B1",...},{"id":"B2",...}]`
