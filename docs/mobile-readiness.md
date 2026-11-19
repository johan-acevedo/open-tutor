# Mobile readiness: assessment and proposed next pass

Status: assessment only, 2026-11-04, against `milestone-a/live-loop` @ `7592b4a` (PR #2). No code changed.

**Evidence levels.** *Source* means read in this repo. *Documented* means taken from a vendor document or bug tracker, linked below. *Device* means tested on a real phone. Nothing here is device evidence yet. The milestone A browser runs used desktop Chromium with a fake microphone. They say nothing about phone audio.

## Summary

A phone version does not need a native app or push-to-talk. The SDKs already handle most of the transport. The work is in three areas:

1. **Layout.** The page is built for desktops. At phone width the board is too narrow to read. This is a fixable CSS and markup pass.
2. **Starting audio and recovering it.** iOS can start a call with no tutor sound and give no indication. This needs a small amount of code.
3. **Echo and turn-taking on speakerphone.** This is the real uncertainty. Several settings will help, but only phone tests can tell how good it gets. We cannot promise zero echo.

## 1. Layout (source; projected, not rendered)

- **One breakpoint.** `styles.css:861` (≤1024px) fixes the avatar column at 180px. `.ot-main` is always a row. At 390px portrait the board gets about 140px (390 − 48 padding − 24 gap − 180), so 32px equations show through a horizontal scroll slot.
- **Arrival.** The 56/44 split is even tighter at this width.
- **Tablet.** At about 820px portrait the board gets about 568px and is fine. It is the only small screen that works today.
- **Landscape phone (844×390).** The 48px top bar and 64px bottom bar leave about 270px. In-flow banners take more. The resource and HTML frames have `min-height` 320–360px (`styles.css:650`, `Cards.tsx:151`), so they push past the viewport.
- **Viewport and keyboard.** The viewport meta lacks `viewport-fit=cover` and `interactive-widget` (`index.html:5`). There is no `env(safe-area-inset-*)` anywhere, so the home indicator and notch can overlap the bottom bar. The root already uses `100dvh`, which is good. On iOS the keyboard overlays the page by default, so the bottom bar can sit under it while the child types. There is no `visualViewport` handling.
- **Controls stability.** The caption is clamped to 2 lines, but `min-height:1.5em` lets it grow from 1 line to 2. That resizes the avatar. Pill labels vary in length ("Pratar" vs "Väntar medan du tittar").
- **Bottom bar at 390px.** The text field shrinks to about 100px.
- **Touch targets.** These pass at 44px except `.ot-resource-open` (about 42px). There are no hover-only interactions.
- **Uploads.** The file input has `accept=".pdf,.png,.jpg,.jpeg,.webp"` and `multiple` (`App.tsx:156`). The picker works, but a MIME-type accept (`image/*,application/pdf`) is the more reliable way to make phones offer the camera as well as the library. iPhone HEIC photos still need verifying on a device. The paste handler is fine. The dropzone copy ("Släpp en fil…") means nothing on touch.
- **Memory.** IndexedDB profiles with a fallback to in-memory storage (`db.ts:23-41`) work on phones.

## 2. Live voice (source and documented)

**Already in place (source)**

- Client: `livekit-client` 2.23.0.
- `new Room()` with defaults (`useSession.ts:229`) leaves the browser's echo cancellation, noise suppression and auto gain on.
- `setMicrophoneEnabled(true)` is called after `connect()`. A denied microphone already falls back to typing with the amber banner.
- There are reconnecting and disconnected banners, and the SDK already does ICE restart and the TURN/TCP/TLS fallback ([connect docs](https://docs.livekit.io/intro/basics/connect/)).
- Agent: `livekit-agents ~=1.8.10`, Silero VAD, STT endpointing (0.6–4.0 s).

**Gaps that matter on phones**

1. **Silent tutor on iOS (P0).** `room.startAudio()` runs only after two network awaits: the `/api/session` fetch and `room.connect` (`useSession.ts:204,377,383`). By then iOS may no longer treat the original tap as a user gesture. Its failure is swallowed, and there is no `RoomEvent.AudioPlaybackStatusChanged` handler. LiveKit's documented pattern is a start-audio button driven by that event ([Room reference](https://docs.livekit.io/reference/client-sdk-js/classes/Room.html), [StartAudio](https://docs.livekit.io/reference/components/react/component/startaudio/); a related iOS no-sound report is [client-sdk-js#1133](https://github.com/livekit/client-sdk-js/issues/1133)). The fix:
   - unlock the `<audio>` element synchronously in the Starta tap;
   - add a one-tap "Tryck för att höra mig" recovery driven by the event.
2. **Interruption mode (P0).** The agent pins `interruption={"mode": "vad", "min_duration": 0.4}` (`agent.py:405`). Any 0.4 s of voice activity cuts the tutor off. On speakerphone that includes the tutor's own voice when echo cancellation leaks, and also coughs and "mm". Current LiveKit Agents offer `mode: "adaptive"`, which separates real interruptions from backchanneling. Its docs say it is the default only on LiveKit Cloud agents or in dev mode, so a self-hosted worker like the ThinkCentre one must set it explicitly. They also offer `min_words` (with STT) and `resume_false_interruption` ([turns docs](https://docs.livekit.io/agents/logic/turns/)). Two things are unconfirmed: whether adaptive mode is available in 1.8.x, and whether it costs anything.
3. **No agent-side noise cancellation (P0 decision).** `session.start` has no `noise_cancellation` (`agent.py:480`). On LiveKit Cloud the noise-suppression models (Krisp NC, ai-coustics QUAIL_L) cost nothing extra; voice isolation (Krisp VIVA, Voice Focus) costs extra. Don't stack frontend and agent models. The browser echo cancellation stays on alongside them ([noise cancellation docs](https://docs.livekit.io/transport/media/noise-cancellation/)). This improves STT and turn detection with a TV or a sibling in the room. It is not an echo canceller.
4. **iOS audio session (P1).** Safari's `navigator.audioSession.type = "play-and-record"` declares a real-time call. It is experimental, Safari-only, and needs feature detection ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/AudioSession/type), [WebKit 16.4](https://webkit.org/blog/13966/webkit-features-in-safari-16-4/)). It is cheap to set before enabling the microphone. Whether it improves echo or audio routing has to be measured.
5. **Speakerphone echo (device test).** WebKit has a history of echo regressions on iOS ([239285](https://bugs.webkit.org/show_bug.cgi?id=239285), [239860](https://bugs.webkit.org/show_bug.cgi?id=239860)). Android Chrome's echo cancellation is mature but varies by device. The ways to reduce echo are:
   - keep browser echo cancellation on;
   - set the capture defaults explicitly and log `getSettings()` per session, so test reports show what actually applied;
   - use adaptive interruption;
   - add the copy hint "hörlurar hjälper" ("headphones help").
6. **Route changes (P1).** There is no `devicechange` handling. A Bluetooth headset connecting mid-call should keep the microphone working, or show a one-tap re-enable.
7. **Background and lock (P1, mostly UX).** iOS mutes or ends microphone capture when Safari goes to the background, and the lock screen behaves the same ([WebKit 204681](https://bugs.webkit.org/show_bug.cgi?id=204681), [226620](https://bugs.webkit.org/show_bug.cgi?id=226620)). The Screen Wake Lock API keeps the screen on but does not keep the microphone alive. Planned handling:
   - On `visibilitychange`, pause the tutor, which treats it as quiet time.
   - On return, re-assert the microphone and show a "Välkommen tillbaka" state.
   - Request a screen wake lock during the session so the phone doesn't auto-lock during quiet work.
   - Watch for microphone tracks that end or mute while the room stays connected. Today the UI doesn't see this.

## 3. Proposed changes, prioritised

**P0: needed before handing a phone to a child**

1. A stacked layout for widths up to about 640px:
   - Top: a slim companion strip, about 96–120px, with a head-and-shoulders crop, the pill and a 2-line caption. The companion faces the learner, or turns down and inward toward the board.
   - Middle: the board at full width, scrolling.
   - Bottom: the bar.
   Phone landscape uses a narrow side strip (about 140px) with the creature turned toward the board.
2. Viewport and keyboard:
   - Add `viewport-fit=cover` and `interactive-widget=resizes-content`, plus safe-area padding on the root and the bottom bar.
   - Use `visualViewport` as a fallback for iOS, keeping the bar above the keyboard.
   - On keyboard open, collapse the companion strip to pill and caption only.
3. Audio unlock in the tap, plus a playback-blocked recovery button.
4. Agent interruption: adaptive mode if available, otherwise `min_duration` 0.5–0.6 s with `min_words`. Add agent-side Krisp NC.
5. Cap frame heights at `min(320px, 45dvh)`.

**P1**

- Reserve a fixed 2-line caption height.
- Raise the type floor to 15–16px on phones.
- Make Avsluta more compact so the text field gets at least 160px.
- Use a MIME-type `accept`. Under `(pointer:coarse)`, change the dropzone copy to "Tryck på 📎 eller fota läxan".
- Set `play-and-record`.
- Log capture settings explicitly.
- Handle `devicechange`.
- Handle visibility and lock, re-assert the microphone, and use a wake lock.
- Add `online`/`offline` banners.

**P2**

- Resource link at 44px or more.
- Move the toast below the top bar.
- Add an `svh` fallback.
- Per-session phone telemetry: audio route, applied settings, barge-in latency.

**What the SDK already does (don't rebuild)**

- signalling and ICE reconnect, and network fallback;
- default echo cancellation, noise suppression and auto gain;
- track re-publish after reconnect;
- the `canPlaybackAudio` state, which only needs a UI.

## 4. Mockups: a small, targeted round helps

Use mockups only where the phone layout is new. Desktop images can't answer the strip-vs-board question, and the creature's crop and gaze change at this size.

1. **Phone portrait, greeting**, at 390×844. The companion is larger in arrival, the Starta/attach path is above the fold, and there is no keyboard.
2. **Phone portrait, active maths/homework.** Shows a slim companion strip on top, a paper card plus worked steps at full width, a highlighted row, and the caption.
3. **Phone portrait with the keyboard open.** The strip is collapsed to pill and caption, and the bar sits above the keyboard.
4. **Phone landscape, resource video.** Shows the side strip with the companion turned toward the video and the "Väntar medan du tittar" state.
5. Optional: **phone permission/recovery.** "Tryck för att höra mig" or the blocked-microphone banner plus typing. This is cheap enough to design directly in CSS, so only render it if the others go well.

Quiet work is skipped: it is the same as image 2 without the wave. The tablet is skipped because the current 180px column works.

Art direction: adapt the existing style guide prompt rather than replacing it.

- Same slate canvas and paper cards.
- The same blue creature: **no wings**, amber eyes, navy hoodie, orange neckerchief.
- Its gaze is at the learner or inward toward the board, **never outward**.
- No voice wave unless it is speaking.
- Phone frame with safe areas shown.

## 5. Proposed sequence

1. **Mockups 1–4.** One round. Johan picks the strip treatment.
2. **One focused implementation PR** after #2 merges, containing the P0 items and the cheap P1 items. Test it with Playwright at 390×844, 844×390 and 820×1180 for layout only, plus unit tests for the playback-status state.
3. **Real phone and audio testing.** Devices × routes × scenarios:
   - Devices: Johan's actual phones, plus a desktop control.
   - Routes: speakerphone, wired earbuds, Bluetooth.
   - Scenarios: quiet room, TV or sibling noise, barge-in ×3, 30 s quiet work, Wi-Fi→cellular, 60 s in the background then return, lock, a Bluetooth headset connecting mid-call, and microphone denied then allowed.
   - Pass when the greeting arrives within 8 s and the tutor never interrupts itself from its own echo.
   - Measure barge-in latency, and recover without a full restart where possible.
   - Record results in `docs/` with an explicit device or emulation label.
   Then tune the interruption and endpointing values from real sessions with the children.

## Open question

Which phones and tablets will the children actually use: iPhone or Android, which models, and do they own headphones? This sets the test matrix and how hard to push on speakerphone echo.
