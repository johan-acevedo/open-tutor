# Landing page, November 2026

Owner review, 2026-11-24. Johan wanted to invite more people and found the voice-first start page
(`design/bands/landing-exploration/`) experimental-looking next to polished product pages: lots of
dead space, no statement of what the product is, and a disclaimer-like note under the button.

## Files

- [mockups.html](mockups.html): first pass, three directions (A dark split hero, B centred stage,
  C light and warm). Johan chose A.
- [mockup-a2.html](mockup-a2.html): A without pills or fine print, steps reordered, bubble variants.
- [mockup-a3.html](mockup-a3.html): the selected design. Comic bubble with speaker icon,
  numbered step pictures, final copy.

## Decisions (Johan, 2026-11-24)

- No pill/chip row above the headline and no small statements under the call to action. When
  removing such elements, rebalance the layout (type scale, spacing, where the information
  lives) instead of leaving a hole. No gradient text.
- Steps read as a flow: Visa läxan → Prata med {companion} → Lös den ihop.
- The bubble only says "Hej!" (returning: "Hej {name}!"), drawn as a comic speech bubble with a
  dark outline, a big tail and a static speaker-with-waves icon. Static before the call.
- Copy calls the product an AI ("en AI för dig som går i åk 1–6"), not an "AI-tutor", which
  the audience doesn't know. It is a free experiment ("Gratis medan vi testar"); it does not
  promise open source or non-profit.
- Returning visit: "Inte {name}?" sits on the same row as the start button.
- Menu: "Så funkar det" scrolls to the steps, "Om Open Tutor" and "Integritet" open the
  existing notes.
- The fox greeting needs a higher-resolution source for the hero (option b: regenerate rather
  than shrink the hero).

## Copy per band

| Band | Intro | Cross-links |
| --- | --- | --- |
| Räven (åk 1–6) | Räven är en AI för dig som går i åk 1–6. Den lyssnar, förklarar och ritar på tavlan medan du själv löser uppgiften. Gratis medan vi testar. | Går du på högstadiet? Prata med Lodjuret. Gymnasiet eller vuxen? Prata med Björnen. |
| Lodjuret (högstadiet) | Lodjuret är en AI för dig som går på högstadiet. … | Yngre? Prata med Räven. Gymnasiet eller vuxen? Prata med Björnen. |
| Björnen (gymnasiet, vuxna) | Björnen är en AI för dig som går på gymnasiet eller pluggar som vuxen. … | Yngre? Räven tar åk 1–6 och Lodjuret högstadiet. |

The mockups load fonts from Google Fonts and images by absolute local path; they are design
records, not served pages.

## Iterations A4–A5 (Johan, 2026-11-24, evening)

- A Gemini 4 Neon review (via `agy` CLI) of the live A3 page found the start button below the
  fold on common phones, the bubble's tail in the fox's eye, a header off the content grid and
  tight headline tracking. All fixed in A4.
- Johan: the page felt cramped next to the mockup. A4 shows the grid only behind the companion,
  lets the hero fill the first view and leaves wide space before "Så funkar det".
- Copy: "Gratis än så länge" (free for now, not "while we test"); step 1 shows one simple
  example ("Fota uppgiften, så ser {companion} den också.") rather than every way to share work.
- The bubble plays a short greeting in the call voice when tapped (`web/public/audio/`,
  `scripts/make_hello_clips.sh`).
- Cross-links left the hero for cards after the steps. A5: the audience ("Högstadiet") is the
  big label and the companion is secondary; zoomed-in faces; big tap targets.
- A5: lynx and bear must carry the same visual weight as the fox; step 2 uses a talking bubble
  with dots instead of voice bars; step 3 drops the operation labels (primary:
  30 + 40 = 70 → 6 + 7 = 13 → 70 + 13 = 83).

## Design v2: warm palette and portrait chooser (2026-11-26)

Johan found live v1 "okej men långt ifrån hur bra det kan bli" and the blue/purple AI-slop-like,
clashing with the warm flame mark. v2 moves the brand pages and the primary band to the warm
Talarum palette (`design/STYLE-GUIDE.md` §4) and rebuilds the `/` chooser as three companion
portraits (transparent heroes on band-coloured backdrops, a comic "Hej!" bubble as the listen
affordance, cream buttons on one baseline). Decisions above still hold: no pills above the
headline, no gradient text, no fine print under buttons, one tap from card to call.
