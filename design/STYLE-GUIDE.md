# Open Tutor — Visual Style Guide (Draft)

Status: working draft for initial implementation and next mockup pass.
Target: desktop browsers on school Chromebooks (`1366×768`) and Windows PCs (`1920×1080`).

## 1. Agreed Constraints vs. Proposed Visual Choices

### Agreed constraints (Founding Brief & PRD)
- **Context:** Swedish children aged 9–15 doing real homework in a browser. No install, login, parent dashboards, billing, or marketing pages.
- **Continuity:** Local sibling profiles (`namn` + `årskurs`) and brief session notes. Fresh board each visit.
- **Live call:** One tap starts session and mic. No push-to-talk; interruptible mid-sentence. Quiet intervals for thinking, reading, writing, or video are normal.
- **Spatial roles:** Large original companion on arrival; moves aside so the AI-controlled whiteboard takes the main area.
- **Character direction (confirmed for the second pass):** Keep the blue companion, remove its wings, and face it toward the learner or inward toward the board. Its gaze must never point out of the screen.
- **No child board or essay editor:** Students write essays in school documents or on paper, pasting excerpts or dropping photos/PDFs into the session.
- **Fixed controls & captions:** Permanent bottom bar (attach, text input, mic toggle, `Avsluta`) outside generated board content. Short live caption under avatar; no full transcript.

### Proposed visual choices (open to iteration)
- **Dark studio slate canvas** with faint grid, plus **warm off-white paper cards** for uploaded homework and pasted text.
- **Restrained cyan and violet accents** for pedagogical focus and interactive states, not decorative chrome.
- **Character:** Retain the blue creature from the first mockups, with no wings and simpler clothing. The original three-candidate sheet remains a record of exploration.

## 2. Critical Review of the First Mockups

### What helps learning (keep)
- **Calm studio atmosphere (`01-profiles-v2`, `02-greeting`):** Dark gridded canvas feels game-adjacent and focused without corporate SaaS or babyish gamification.
- **Maths clarity (`04-maths`):** High-contrast white equations with one translucent cyan highlight (`3x = 15`) and balance operations (`−5`, `÷3`) make spoken steps easy to scan.
- **Paper-on-board contrast (`03-homework`, `05-book-review`):** Photographed worksheets and pasted drafts sit on warm off-white cards, separating *student material* from *tutor board work*.
- **Patient stillness (`06-quiet-work`, `07-resource`):** Closed mouth, folded hands, and no voice wave during calculation or video playback communicate unhurried presence.

### What distracts or misleads (change)
1. **Avatar never shrinks (`03`–`08`):** Generator locked onto `02-greeting`'s 58/42 split. Rävdrake takes ~42% width in every view, cramping the board and shrinking the worksheet in `04-maths` into a tiny sticky note.
2. **Contradictory waveforms (`03`, `05`, `10`):** `05-book-review` shows `Lyssnar` with closed mouth, yet renders equalizer bars and a glowing voice wave under the caption. `10-mic-blocked` also shows a voice wave while waiting for text. Voice waves belong **only** in speaking states.
3. **Excessive neon chrome:** Gradient bars under headings, angled frames around `Leo · åk 8` (even pre-call in `01-profiles-v2`), dashed boxes around every board, and glowing sleeve circuits dilute focus.
4. **Render artifacts:** Remove `®` on `Open Tutor`, cartoon pushpins (`04`, `05`), `villl...` (`05`), and `"Etene"` instead of **"Eten"** (`07`).

## 3. Design Character & Age Appeal (9–15)

Aim for **competent indie-game companion meets calm study desk**—original and polished without copying copyrighted IP.
- **Older learners:** Avoid toddler proportions, confetti, streaks, stars, or XP bars (`08-understanding` limits celebration to a clean green card). Creature companions work for 15-year-olds with composed posture, grounded clothing (hoodie, jacket, scarf), and understated reactions.
- **Avatar discipline:** Remove wings completely. Keep clothing details restrained and the tail within the character column. On the right side, the character looks into the camera or turns toward the left-hand board. Keep listening and waiting poses relaxed. Do not add floating props behind its head.

## 4. Semantic Color Palette

Strip back gradients so color carries strict meaning:
- **Canvas primary (`#181B22`):** Background with `24px` grid (`#FFFFFF08`, 3% opacity).
- **Elevated surface (`#222731`):** Cards and bottom bar (`#14171D` with `#2E3543` 1px border).
- **Paper surface (`#F6F4EE`):** Homework photos, PDFs, and pasted drafts (`#181B22` ink).
- **Text primary (`#F3F5F8`) & secondary (`#9BA3B4`):** Equations/headings vs. labels and static waiting copy.
- **Focus Cyan (`#22D3EE`):** Active step (`#22D3EE1F` fill), speaking indicator, `Starta` CTA, input focus ring.
- **Teaching Violet (`#A78BFA`):** Step arrows, mind-map connectors, `Tänker / Ritar…` state.
- **Verified Green (`#34D399`):** Correct result border (`#34D39945`) and check mark (`08`).
- **Caution Amber (`#F59E0B`) & End Red (`#DC4A4A`):** Warning banner (`10`); red strictly for `Avsluta` (`#B93838` fill).

## 5. Typography, Swedish Copy & Maths

- **UI & Board Sans:** `Plus Jakarta Sans`, `Inter`, or system `Segoe UI` / `Roboto` with full Swedish coverage (`å, ä, ö, Å, Ä, Ö`).
- **Mathematics:** KaTeX or tabular numerals (`font-variant-numeric: tabular-nums`). Distinguish italic *x* from `·` / `×`, true minus `−` (`U+2212`), division `÷` or horizontal fractions (`03`), and `1` vs `l`.
- **Scale (`1366×768`):** Title `28px–32px` (`600`, no underline bar); equations `28px–36px` (operations `20px` in `#22D3EE`); body/drafts/captions `18px` (`1.5` line-height, max `65ch`); pills `14px–15px` (`500`).

## 6. Proportions, Spacing & Smaller Windows

Target **`1366×768` (`16:9`)** with `24px` outer padding:
- **Top bar (`48px`):** Plain `Open Tutor` wordmark left; rounded pill (`Leo · åk 8`) right, shown **only after profile selection**.
- **Arrival & Greeting (`01`, `02`):** **56% board / 44% avatar.** Large waist-up character. `01-profiles-v2` hides the bottom bar.
- **Teaching & Resources (`03`–`08`, `10`):** **74% left board / 26% right avatar column** (`max-width: 340px`). Scale character down ~30% (chest-up, no wings) so the board holds both homework and worked steps.
- **Split-screen (`720px–1024px` wide):** Students writing in Google Docs often snap Open Tutor to half their Chromebook screen. Below `1024px`, compact the right column to `180px` (head-and-shoulders + pill + caption) so the board keeps ≥70% width.
- **Containers:** Vertically scrollable board. Dashed borders **only** for drop zones (`02`) and `Ritar…` placeholders (`04`).

## 7. Stable Controls, Cards & Captions

- **Fixed bottom bar (`64px`):** Always visible in-session; never covered by generated content. Holds `Lägg till läxa` button (`44×44px`), `Skriv här om du vill…` field, round mic toggle (`44×44px`), and red `Avsluta` button.
- **Homework & draft cards (`03`, `04`, `05`):** `#F6F4EE` paper surface, `12px` radius, clean header (`matteprov.jpg`, `Ditt utkast · inklistrat`) without pushpins. Keep uploaded problems readable alongside worked steps.
- **Resource player (`07`):** Embedded video/reading on board with standard controls and one prompt chip below (`Fundera på: ...`).
- **Live caption:** Max 2 lines (`18px`) under status pill; shows current spoken sentence and fades 3s after speech stops.

## 8. Session States & Non-Color Cues

Combine **avatar pose**, **pill icon**, **Swedish label**, and **motion vs. stillness**:
- **Pre-call (`01`):** Friendly smile, mouth closed, profile cards + `Starta`. No status pill, bottom bar, or mic icon.
- **Speaking (`02, 04, 08`):** Pill `Pratar` / `Förklarar` + 3-bar sound icon (`#22D3EE`). Lip-sync + board gesture. Subtle wave **only while audio plays**.
- **Listening (`05`):** Pill `Lyssnar` + ear/ring icon (`#22D3EE`). Head tilt, mouth closed. **No voice wave.**
- **Thinking / Drawing (`03, 04`):** Pill `Tänker…` / `Ritar…` + sparkle/pencil (`#A78BFA`). Looks at board; dashed `Ritar…` card. **No voice wave.**
- **Quiet Waiting (`06, 07`):** Pill `Jag väntar` / `Väntar medan du tittar` + circle/hourglass (`#2E3543`). Hands folded, mouth closed, slow blink. Static helper or empty caption.
- **Child Muted:** Slashed mic on `#222731` button (`Mikrofon av`, no cyan glow); tutor waits or listens to text.
- **Mic Blocked (`10`):** Amber banner (`#F59E0B`) + `Försök igen`; slashed mic; text field focused (`#22D3EE`); pill `Väntar på text`. **No voice wave.**
- **Disconnected:** Amber banner `Tappade kontakten – försöker igen…`; avatar stills in waiting pose; board stays scrollable.

## 9. Motion, Voice Sync & Accessibility

- **Speech-visual sync:** Highlight active equation row or diagram node as the tutor names it. Show a compact `Ritar…` card while slower visuals generate.
- **Quiet presence:** One region moves at a time. During quiet work (`06`) or video (`07`), freeze UI loops and waveforms; only a natural blink remains.
- **Accessibility:** ≥7:1 contrast on `#F3F5F8` board text and `#181B22` paper ink. Under `prefers-reduced-motion: reduce`, disable sway, waveforms, and animated transitions.

## 10. Reusable Image-Generation Art-Direction Paragraph

> Flat front-on 16:9 desktop browser UI (`1366×768`) for Swedish learners aged 9–15, deep slate-charcoal background (`#181B22`) with faint 24px grid, crisp flat UI with 1px solid borders (`#2E3543`), no neon HUD frames, gradient underlines, or trademark symbols. Top-left wordmark "Open Tutor", top-right rounded pill "Leo · åk 8". Teaching views use a 74% left whiteboard / 26% right companion column (`max-width: 340px`). Right side: compact chest-up 3D creature companion (slate-blue creature, amber eyes, navy hoodie, orange neckerchief, no wings or glowing sleeve circuits; gaze at the learner or toward the left-hand board, never outward) with one status pill and 1-line Swedish caption below. Render a voice waveform ONLY when speaking; keep listening, thinking, and waiting states waveform-free. Uploaded homework and pasted drafts sit on warm off-white paper cards (`#F6F4EE`) with dark ink and no pushpins. Fixed bottom bar (`#14171D`) with attach button, input "Skriv här om du vill…", round mic toggle, and red "Avsluta" button.

## 11. Next Mockup Refinements & Kid Testing

- **Mockup refinements:** (1) Enforce 74/26 split in `03`–`08` (make the wingless companion compact, gaze inward or at the learner); (2) remove false voice waves in `05` and `10`, replace `Lyssnar` equalizer icon with ear/ring icon, fix `villl...` in `05`; (3) hide `Leo · åk 8` in `01-profiles-v2`, replace purple sticky note in `04` with a homework card, fix `"Etene"` to **"Eten"** in `07`, and remove `®`.
- **Test with the kids:** Check how the revised wingless companion feels during a lesson, including direct eye contact versus glancing toward the board during quiet work. Observe split-screen layout alongside Google Docs on a Chromebook.
