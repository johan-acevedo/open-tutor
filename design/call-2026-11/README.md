# In-call view, November 2026

Owner review, 2026-11-24 evening. After the landing page (`design/landing-2026-11/`) the call view
no longer held the same quality: everything pinned to the edges, a large empty board at call
start, a cramped top bar (48 px bar, 44 px buttons), a full-page grid, and a 1600 px text field
that read like a chat app. A Gemini 4 Neon review (via `agy` CLI) agreed.

[mockups.html](mockups.html): concept A (frames A1–A3) and the rejected concept B.

## Decisions (Johan, 2026-11-24)

- **Concept A.** The call starts with the companion large and centred (halo, no empty board).
  The board slides in on the left (~2/3) only when there is something to show; the companion
  moves to a right-hand column and stays large: it must be big enough to show what the AI is
  doing (its poses) and carry a speech bubble with the caption and the state.
- **Avsluta moves into the bottom control dock** (reverses the 2026-11-11 top-bar placement).
- **Phone: the companion stays beside the board**, as today. It does not become a strip above
  the board (frame A4 in the mockup is rejected).
- Grid only as a halo behind the companion, as on the landing page.
