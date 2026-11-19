# Open Tutor: product requirements (first draft)

Status: draft, 2026-11-03; age bands added 2026-11-18; voice-first start added 2026-11-19. Intent comes from the founding brief in [README.md](README.md). This document describes what a learner should experience; technical design is separate work. "Child" below covers every band; gymnasiet students and adults (band 3) are in scope since 2026-11-18.

**Agreed** marks what the brief or Johan has stated. **Default** marks a proposal we build unless someone objects, and change after real sessions. Open decisions are in section 5.

## 1. Goal of the first release

Johan's children (9–15, Sweden) can open a browser page on a school Chromebook or Windows PC on an ordinary weekday, bring real homework, and work through it in Swedish with a live voice tutor who explains, asks, draws, and helps them do the work themselves.

Success: they find it helpful, understand something new, and come back on their own.

Since 2026-11-18 the same codebase also serves högstadiet (`tutor2.*`, åk 7–9)
and gymnasiet plus adults (`tutor3.*`): one band per host, picked by the
request host, deciding the look (companion, theme, copy). The band never
switches mid-session or on later visits; unknown hosts default to band 1
(åk 1–6). Companion art and themes for bands 2 and 3 are still placeholders
(the fox, with distinct theme tokens); see `design/bands/README.md`.

## 2. First learner journey

1. The child opens the URL. No install, no login, no access code.
2. First visit: the companion, a static welcome bubble ("Hej! Ska vi prata?") and one "Prata med {companion}" button. No name field, no profile grid, no grade picker. The tutor asks for the name by voice after starting, repeats it back to confirm, and saves it; a typed name and a voice correction recover from mishearing. The next visit assumes the same student: "Hej <name>, ska vi köra?" with the same button, plus a small "Inte <name>? Byt" link. "Byt elev" (band 3: "Byt person") lives behind the hamburger menu and returns to the nameless first visit. Profiles stay in browser storage.
3. One tap starts the session and grants microphone access. This is the only setup step.
4. A large tutor character fills the page and **speaks first**: a greeting, a mention of last time if there was one, and an invitation to share what they're working on.
5. The child talks, types, drops a file or photo, or pastes a screenshot or text. The homework appears on the board where both can see it.
6. They work. The tutor explains on the board while speaking, asks what the child thinks, stays quiet while the child writes or calculates, and suggests a short video if one would help.
7. When the child understands something, the tutor notices and celebrates it. If the child is interested, it offers a next step.
8. The child says they're done or presses "Avsluta". The tutor sums up in a sentence or two. What they worked on is saved in this browser for next time.

## 3. Requirements

### 3.1 Arrival and profiles

- Agreed: no accounts, no registration. Profiles live in browser-local storage. Siblings on one browser each have their own profile. Clearing browser data loses them.
- Agreed: a new child can start immediately.
- Default: a profile holds a first name, a school year (null until known), and the tutor's notes on past sessions. No PIN between siblings.
- Default: the school year sets the tutor's register. A 15-year-old is spoken to like a young adult; a 9-year-old gets simpler language and smaller steps. An unknown school year defaults to the band until the tutor learns it (åk 1–6 / högstadiet / gymnasiet-or-adult).
- Agreed (2026-11-19): the call starts with no name. The tutor greets without one, asks the learner's name early, repeats it back to confirm, and stores it with the `set_learner_name` tool — creating the local profile, or attaching to an existing local profile with the same name — so later visits start with it. A correction later is the same tool call again. If the microphone is blocked, typing the name works; if the tutor mishears, the learner corrects by voice or by typing.
- Agreed (2026-11-18): if the grade is unknown, the tutor finds it out naturally early in the first call — never as a form; inferring it from shared homework counts — and stores it with the `set_learner_grade` tool, so the browser profile and later calls start with it. On band 3 the tutor finds out naturally whether the learner is a gymnasiet student (and which year) or an adult; only adults skip the grade, and the tutor asks what they are working on.
- Agreed (2026-11-18): if someone else takes over ("this is Leo now"), the tutor confirms, asks the name when it is new, then switches via the `switch_student` tool: the current lesson ends like Avsluta (its note saved for the current student), and the start page then shows the other student's name with one Starta button. Their own notes load when their lesson starts.

### 3.2 Live call and presence

- Agreed: after the first tap the session behaves like a call. No push-to-talk. The child can interrupt the tutor mid-sentence, and the tutor stops and listens.
- Agreed: the tutor follows the session continuously. It speaks when addressed, or when it has something useful enough to add. It does not fill silence with chatter.
- Agreed: silence for thinking, writing, reading or watching is normal. The tutor waits.
- Agreed: the tutor only sees what the child brings into the session. It does not watch the screen, other tabs, or the camera.
- Default: the character always shows its state: listening, speaking, thinking or preparing a visual, or quietly waiting.
- Agreed (2026-11-03): a short live caption line under the character shows what the tutor is saying, so a missed word can be read. No full transcript in the first release.
- Default: a visible mic button mutes the child (for example when someone else in the room is talking). Muting does not end the session.

### 3.3 How the tutor teaches

- Agreed: a calm, patient older student. Explains directly when that helps; asks questions when that helps. Never turns every difficulty into another question the child cannot answer. Changes approach when an explanation does not land.
- Agreed: helps the child get started and develop their own work. It does not write the essay, book review or answer set for them.
- Agreed: celebrates understanding, follows the child's curiosity, and goes deeper when the child is willing. School year and assignment context orient the conversation; no formal curriculum mapping.

### 3.4 Whiteboard

- Agreed: the tutor controls the board. The child does not draw or edit on it in the first release.
- Agreed: the tutor can show text, equations, diagrams, step-by-step working, organised ideas, and, where useful, layouts, animations and generated images. The medium is the tutor's choice.
- Agreed: speech and visuals stay in step. The tutor does not talk about something the child cannot see yet. A slow visual never stalls the conversation.
- Default: on arrival the character is large. Once there is something to show, the board takes the main area and the character moves to a side panel, still visible and animated.
- Default: a visual that is still being made shows a small placeholder ("Ritar…") while the conversation continues.
- Default: the child can scroll back through earlier board content in the session.

### 3.5 Homework intake

- Agreed: files, photos of paper assignments and tests, pasted screenshots, and pasted text. Exact formats are an implementation detail.
- Default: drag-and-drop anywhere on the page, Ctrl+V anywhere, and an "Lägg till läxa" button. Shared material appears on the board as a pinned card, so the child can see that the tutor has it.
- Default: the tutor confirms what it sees ("Jag ser uppgift 3 och 4 om ekvationer") before working on it.

### 3.6 Resources

- Agreed: the tutor can find and suggest public educational videos and readings, and discuss them afterwards.
- Agreed: no allowlists, approval steps, quality gates or ratings. The model uses judgement.
- Default: a resource opens on the board, inside the page where the source allows it, otherwise in a new tab. While it plays, the tutor stays quiet and does not respond to the video's sound. When it ends, or the child speaks, they talk about it.

### 3.7 Language

- Agreed: Swedish for the first release, across subjects such as maths, religion, social sciences and chemistry.
- Agreed: the best-sounding Swedish voice wins. Gender does not matter.
- Agreed (later): English, Spanish and mixing languages. Not a blocker for the first release.

### 3.8 Stable controls

- Agreed: a permanent text input and call controls sit in a fixed part of the layout, outside the board's generated content. Nothing the tutor generates can cover or move them.
- Default: bottom bar with text field ("Skriv här om du vill…"), attach, mic on/off, and "Avsluta".

### 3.9 Continuity

- Agreed: the tutor remembers the learner across visits in the same browser.
- Agreed (2026-11-03): at the end of each session the tutor saves a short note: topic, what clicked, what is still tricky, what to try next. On return, the greeting draws on it. A new session starts with a fresh board; the previous board and files do not carry over.

### 3.10 Character

- Agreed: one original character per band (several companions are in scope since 2026-11-18), large and welcoming on arrival. Band 1's is inspired by the children's interests (Minecraft, Fortnite, Roblox, Naruto, One Piece, Among Us, Geometry Dash) without copying any of them. It must work for both a 9-year-old and a 15-year-old.
- Agreed for the second mockup pass: retain the blue game-inspired companion, remove its wings, and have it face the learner or look inward toward the board. It must never look out of the screen. Keep its appeal across ages open to feedback from the children.

### 3.11 Hosting and providers

- Agreed: browser only; credentials stay on the backend; speech and model providers are swappable, and others can run it with their own. Local memory does not mean local inference: session content goes to the backend and chosen providers.

## 4. Out of scope for the first release

Accounts, cross-device sync, parent dashboards or parent instructions, billing, resource ratings or approval, child editing of the board, curriculum integrations, screen or camera watching, English and Spanish teaching, and polished onboarding or marketing pages.

In scope since 2026-11-18 (contrary to earlier drafts): adults as learners, and one companion per age band.

## 5. Open decisions

1. **Character refinements**: the blue companion continues without wings; remaining details are refined through the next mockups and use with the children.
2. **Open-source licence and contribution process.**

Settled 2026-11-03: the child writes long work (book review, essay) where school expects, in the school document or on paper, and pastes or photographs drafts back. Open Tutor has no writing area in the first release.

## 6. Ready for a real session

Before a child uses it unsupervised on homework, Johan should be able to check each item on a school Chromebook and on the Windows PC:

- From opening the URL to hearing the tutor greet takes no more than about 15 seconds and one tap (returning: one tap on "Hej <name>, ska vi köra?").
- Saying "vänta" mid-sentence stops the tutor promptly.
- A 30-second silence while the child calculates does not make the tutor speak, unless it says one short, useful thing.
- A pasted screenshot, a dropped PDF and a phone photo of a handwritten maths test each appear on the board, and the tutor describes them correctly.
- In a maths explanation, the board shows the step the tutor is talking about at the time it is talking about it.
- A slow visual does not leave more than a couple of seconds of dead air.
- Asked to "just write my book review", the tutor declines kindly and helps the child start their own.
- A suggested video plays on the page without the tutor talking over it, and they discuss it afterwards.
- Spoken Swedish is easy to understand and does not sound robotic to the children.
- Two siblings use the same browser; each gets their own greeting and memory.
- Closing the tab mid-session and returning keeps at least the profile and earlier notes.
- If the microphone is blocked, the page says so in Swedish and typing still works.

## 7. Mockup coverage

Raster mockups to generate after clarification, one image per state.

**Visual defaults** (from Johan's sketch): 16:9 at Chromebook size (1366×768). Dark charcoal background with a faint grid. Cyan-to-violet gradient accents. Board on the left, character on the right. Rounded, friendly sans-serif type. Fixed bottom control bar. All copy in Swedish. Fictional learner names (Elsa, åk 4; Leo, åk 8). The character is original; no recognisable game or anime IP.

| # | View / state | What it must show | Suggested Swedish copy |
|---|---|---|---|
| 1 | Voice-first start | Static welcome bubble, one start button, no name field; returning visit: "Hej <name>, ska vi köra?" with an "Inte <name>? Byt" link; switch behind the menu returns to the nameless first visit | "Hej! Ska vi prata?" · "Prata med Räven" · "Hej Leo, ska vi köra?" · "Inte Leo? Byt" · "Byt elev" |
| 2 | Greeting | Large character speaking, empty board hint, caption, bottom bar | "Hej Leo! Förra gången körde vi ekvationer. Vad har du med dig idag?" · "Släpp en fil eller klistra in (Ctrl+V)" |
| 3 | Homework arrives | Photo of a handwritten maths test pinned on the board, character confirming | "Jag ser uppgift 3 och 4. Ska vi börja med 3?" |
| 4 | Visual teaching: maths | Board main, character in side panel speaking, equation steps with one step highlighted, "Ritar…" placeholder | "3x + 5 = 20 → 3x = 15 → x = 5" · "Vi tar bort 5 på båda sidor." |
| 5 | Book review coaching | The child's own ideas as a mind map in their words, plus a pasted draft paragraph from their school doc; tutor asking, not writing | "Det du sa om Jonatan" · "Vilken scen minns du bäst?" |
| 6 | Quiet work | Character calm and listening, board showing the task, subtle waiting indicator, mic still live | "Ta den tid du behöver. Jag är här." |
| 7 | Watching a resource | Short chemistry video on the board, tutor in silent "watching with you" state | "Dubbelbindningar på 3 minuter" · "Jag tittar med dig" |
| 8 | Understanding moment | Board shows the child's correct answer, small celebratory touch, offer to go deeper | "Där satt den! Vill du testa en svårare?" |
| 9 | End and continuity | Short spoken summary shown as a card; saved note for next time | "Bra jobbat idag" · "Det här klickade: …" · "Nästa gång: …" |
| 10 | Mic blocked (optional) | Friendly Swedish message, text input still usable | "Jag hör dig inte just nu. Du kan skriva här under." |

The first round explored three character variants. The second pass keeps the blue companion without wings and shows listening, speaking, thinking and quietly waiting poses, facing the learner or inward toward the board.

## 8. Learn through use

The questions in the brief's "What we need to learn" section, plus humour, encouragement and reactions to frustration, are tuned from real sessions rather than specified here.
