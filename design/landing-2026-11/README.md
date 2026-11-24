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
