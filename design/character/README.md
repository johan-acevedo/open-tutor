# Character poses in the app

`web/public/character/*.webp` are transparent cut-outs of the agreed wingless blue companion, taken from the selected mockups. They stand in until a proper character asset pass.

| Pose | Source | Note |
|---|---|---|
| `listening` | `pass-2/00-character.png`, first figure | Mirrored so the gaze points inward (viewer-left) from the right-hand column |
| `speaking` | `00-character.png`, second figure | Frontal |
| `thinking` | `00-character.png`, third figure | Looks toward the board |
| `waiting` | `00-character.png`, fourth figure | Looks toward the board |
| `greeting` | `pass-2/02-greeting.png` | Large frontal welcome, used on arrival |
| `pointing` | `pass-2/04-maths-plain.png` | Points toward the board while explaining |

Rebuild from the repository root:

```bash
python3 scripts/extract_character.py   # cut-out, background removal, crop boxes and mirroring
python3 scripts/clean_character.py     # removes thin streaks, finishes each bust with a soft fade
```

Both need Pillow and numpy. The four sheet poses end in a fade rather than a hard edge, because the sheet's lower edge was ragged after background removal.
