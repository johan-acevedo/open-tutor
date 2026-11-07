# Mobile web: B2 companion

Implementation branch: `feat/mobile-b2`, based on `origin/main` `6bf6678`.
Development and verification run on dell5500. This PR does not change the deployed
family service at https://tutor.labtopia.dev, model, voice, VAD or credentials.

## Experience

Phones have a large bottom-right companion, captions beside its face, and a
separate scrollable teaching area. Landscape uses a right-hand companion rail.
Tablets and desktop keep the existing columns. The child can reduce the companion
explicitly; the keyboard temporarily uses a smaller figure. Very short landscape
keyboard layouts prioritise status and typing.

The latest shown, updated or focused item becomes the teaching card, including
older items. Equation cards reveal through the focused row (first row before
focus); the existing `focus_step` tool advances mobile disclosure. “Hela tavlan”
and “Din uppgift” expose earlier material. Players remain mounted across view
changes. Touch/wheel scrolling pauses following; “Tutorn pekar här” returns to
the current point.

Camera and image/PDF pickers are separate. Mobile files and pasted homework
outside the text field wait in a preview tray for explicit confirmation. Remove,
retake, cancel and retry are available. Ordinary text-field paste stays ordinary
text; desktop intake remains immediate.

Starta prepares audio before profile persistence and network waits. Blocked
playback offers a retry in the same room. Returning from a hidden phone page
offers a resume tap; manual mute is preserved. Browser echo cancellation, noise
suppression and automatic gain are requested. These requests do not prove echo
has been eliminated.

## Browser boundaries

| Area | iPhone / Safari | Android / Chrome |
|---|---|---|
| Audio | Start/resume needs a gesture; background/lock can interrupt media. | Playback permission, audio route and background behaviour vary by device. |
| Keyboard | VisualViewport positions/sizes the workspace; safe-area padding protects controls. | Requests `interactive-widget=resizes-content`, with the same viewport fallback. |
| Photo | `image/*` with `capture=environment` hints at the rear camera. HEIC decoding depends on browser/OS. | Same hint; camera/gallery choices depend on the phone. |
| Files/paste | Uses browser file/clipboard events; undecodable images get JPG/PNG/PDF guidance. | Same routes; document providers and clipboard contents differ. |

Sources checked: [LiveKit playback recovery](https://docs.livekit.io/reference/client-sdk-js/),
[Chrome keyboard behaviour](https://developer.chrome.com/blog/viewport-resize-behavior),
[VisualViewport](https://developer.mozilla.org/en-US/docs/Web/API/VisualViewport),
and installed LiveKit client 2.23.0 source.

## Verification

```sh
npm ci --prefix web
npm run build --prefix web
uv run --with playwright python web/e2e/mobile_probe.py
# Optional real local call, with a local LiveKit server executable:
uv run --project server --with playwright python web/e2e/livekit_probe.py --server /path/to/livekit-server
```

The first probe builds the real app with a **test-only transport alias**.
Production builds do not load it. It exercises 360×800, 390×844, 430×932, 844×390,
820×900, 900×700 and 1366×768: board acknowledgements and focus, history, player
continuity, photo confirmation, keyboard simulation, send focus, recovery and end
confirmation. Its SDK faults, camera file and keyboard are synthetic. Evidence
is written to `.review-checks/mobile/`.

The second uses the ordinary production build and real SDK against a local
LiveKit server (tested with 1.13.11). It checks board/focus RPCs, incoming audio
packets with a running audio context, browser capture settings, muted return and
audio-context cleanup. Input is a fake Chromium microphone, generated tone and
fictional learner. No providers or family rooms are used. Evidence is written to
`.review-checks/mobile-livekit/`.

Neither probe proves audible quality, speakerphone echo handling, child speech,
OS camera/keyboard behaviour or physical iPhone/Safari compatibility.

Real-device checks before relying on phones: iPhone/Safari and Android/Chrome;
arrival and returning child; permission refusal/recovery; camera, gallery, PDF
and HEIC; paste; portrait/landscape keyboard; manual mute across background/lock;
speakerphone interruption/echo; headphones/Bluetooth changes; network reconnect.
Phone VAD tuning follows those sessions, rather than changing the agent now.
