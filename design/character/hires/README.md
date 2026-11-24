# Greeting pose: high-resolution candidates

Date: 2026-11-24.

Three reference-based re-renders of Räven for the landing-page hero. These are review assets. No file under `web/` changes.

## Result and ranking

None meets the strict "same image, only sharper and larger" goal. All retain the recognisable character, friendly gaze, open smile, clothes, and open palms. All change the head-to-hand proportions, eye and muzzle geometry, and clothing details. Do not treat these as an approved replacement.

1. **Candidate 1** is the closest. The softer face and clothing treatment best match the reference. Its cheeks and nose are broader, and its hands are smaller relative to its head.
2. **Candidate 2** has a similar silhouette and gesture. Its more symmetric face, rounder eyes, and stronger smile depart further from the reference.
3. **Candidate 3** has crisp fur and fabric. Its face and garment shapes drift most, with extra garment construction and stronger texture.

The raw renders extend the torso below the original crop. The cut-outs remove that extension and fade the lower sleeves and torso. Cropping does not restore the original proportions.

## Files

| File | Size | Purpose |
|---|---|---|
| `greeting-candidate-1.png` | 1024 × 1475, RGBA | Rank 1, transparent cut-out |
| `greeting-candidate-2.png` | 1024 × 1482, RGBA | Rank 2, transparent cut-out |
| `greeting-candidate-3.png` | 1024 × 1527, RGBA | Rank 3, transparent cut-out |
| `raw/greeting-generated-{1,2,3}.png` | 948 × 1659, RGB | Unmodified generated images |
| `raw/mockup-reference-crop.png` | 572 × 655 | Original mockup crop used as supporting reference |
| `raw/prompts.json` | JSON | Exact complete prompts in candidate order |
| `compare.png` | 4320 × 2340, RGB | Current asset and three candidates on `#181b22`, plus face crops |
| `metadata.json` | JSON | Source checksums, crop coordinates, and output dimensions |
| `rebuild.py` | Python | Reproducible cut-out and comparison processing |

The comparison uses the same 1142 px display height for all figures. The current asset is enlarged 2× with Lanczos. Each lower face panel magnifies a crop of its upper figure by another 2×. The comparison has editorial labels. The companion cut-outs contain no text.

## Tool and references

Generation used the built-in `image_gen.imagegen` tool, with three separate edit requests and `transparent_background=false`. The tool did not expose an underlying model identifier.

Both images were passed as local references, in this order:

1. `web/public/character/greeting.webp`, the identity and pose reference.
2. `raw/mockup-reference-crop.png`, cropped from `design/mockups/pass-2/02-greeting.png` at `(1000, 25, 1572, 680)`.

The requested portrait size was approximately 1536 × 1792. The tool returned 948 × 1659 for every candidate. The final cut-outs use a small Lanczos enlargement to reach 1024 px width. These are generated detail plus resampling, not native 1024 px renders or faithful super-resolution of the original pixels.

## Extraction

`rebuild.py` uses Pillow, NumPy, and SciPy. The extraction follows the existing scripts' separation of foreground and background, largest connected component cleanup, and 10% bottom fade. Chroma green replaces the ambiguous dark background from the original mockup.

The script identifies definite green background and definite foreground, estimates mixed edge pixels from nearby samples, and removes green from those edge colours. It keeps the largest connected component, crops the torso, and applies the fade. It preserves opaque interior colours. Fully transparent pixels have zero RGB.

To rebuild the committed outputs from the preserved raw images:

```bash
uv run --with numpy --with scipy --with pillow python design/character/hires/rebuild.py
```

## Exact prompts

Each request used the same two references listed above. The following text is preserved verbatim. `raw/prompts.json` contains the same strings in machine-readable form.

### Candidate 1

```text
Use case: identity-preserve.
Asset type: Open Tutor landing-page hero companion, high-resolution restoration.
Input image 1 is the EDIT TARGET: the existing transparent greeting.webp cut-out. Input image 2 is a supporting crop of the original mockup to clarify fine details only; ignore its background and stray UI.
Primary request: faithfully restore/upscale exactly the existing character and greeting pose; do not redesign or reinterpret it. Produce a single large portrait image at approximately 1536 x 1792 pixels, with the character filling the frame in the same proportions and framing as image 1. It must look like precisely the same character when placed beside the original in-app poses.
Invariants: same front-facing slate/periwinkle-blue fox-like creature, same large pointed ears and pale pink inner ears, same asymmetric swept three-tuft hair silhouette, same violet/pink brow markings and thick dark brows, same wide amber eyes looking directly at the viewer, same short rounded muzzle and black rounded triangular nose, pale cheek fur, tiny muzzle freckles, same friendly open smile with small pointed teeth and visible tongue, same head/body proportions and facial geometry. Same navy hoodie with cyan zipper/lapel trim, orange neckerchief with the same folds, pale undershirt and tiny gold buttons, small violet outlined downward triangle badge on viewer-left chest. Same waist-up pose with BOTH open palms extended toward the viewer at the bottom, same rounded fingers, hand positions, sleeve folds and camera angle. Keep the existing soft stylized 3D render, lighting direction and colors. Add only faithful sharp detail, not new features.
Backdrop: completely plain perfectly flat chroma-key green #00FF00, including between fingers and beside the silhouette; no shadows or gradients on the green backdrop. This green is absent from the character. Finish torso below the hands so the final cutout can have a soft bottom fade.
Constraints: no wings, no extra fingers, no accessories, no background scene, no props, no text, no letters, no logo, no watermark. The tiny triangle clothing badge is a geometric marking, not a logo to invent.
Restoration priority: match the edit target as exactly as possible; preserve its soft polished surfaces and original expression, with restrained fine fur detail.
```

### Candidate 2

```text
Use case: identity-preserve.
Asset type: Open Tutor landing-page hero companion, high-resolution restoration.
Input image 1 is the EDIT TARGET: the existing transparent greeting.webp cut-out. Input image 2 is a supporting crop of the original mockup to clarify fine details only; ignore its background and stray UI.
Primary request: faithfully restore/upscale exactly the existing character and greeting pose; do not redesign or reinterpret it. Produce a single large portrait image at approximately 1536 x 1792 pixels, with the character filling the frame in the same proportions and framing as image 1. It must look like precisely the same character when placed beside the original in-app poses.
Invariants: same front-facing slate/periwinkle-blue fox-like creature, same large pointed ears and pale pink inner ears, same asymmetric swept three-tuft hair silhouette, same violet/pink brow markings and thick dark brows, same wide amber eyes looking directly at the viewer, same short rounded muzzle and black rounded triangular nose, pale cheek fur, tiny muzzle freckles, same friendly open smile with small pointed teeth and visible tongue, same head/body proportions and facial geometry. Same navy hoodie with cyan zipper/lapel trim, orange neckerchief with the same folds, pale undershirt and tiny gold buttons, small violet outlined downward triangle badge on viewer-left chest. Same waist-up pose with BOTH open palms extended toward the viewer at the bottom, same rounded fingers, hand positions, sleeve folds and camera angle. Keep the existing soft stylized 3D render, lighting direction and colors. Add only faithful sharp detail, not new features.
Backdrop: completely plain perfectly flat chroma-key green #00FF00, including between fingers and beside the silhouette; no shadows or gradients on the green backdrop. This green is absent from the character. Finish torso below the hands so the final cutout can have a soft bottom fade.
Constraints: no wings, no extra fingers, no accessories, no background scene, no props, no text, no letters, no logo, no watermark. The tiny triangle clothing badge is a geometric marking, not a logo to invent.
Restoration priority: keep the exact face and silhouette of the edit target, particularly eye shape, cheek width, muzzle length, hair curves and palm anatomy. Preserve the original soft texture rather than making realistic fur.
```

### Candidate 3

```text
Use case: identity-preserve.
Asset type: Open Tutor landing-page hero companion, high-resolution restoration.
Input image 1 is the EDIT TARGET: the existing transparent greeting.webp cut-out. Input image 2 is a supporting crop of the original mockup to clarify fine details only; ignore its background and stray UI.
Primary request: faithfully restore/upscale exactly the existing character and greeting pose; do not redesign or reinterpret it. Produce a single large portrait image at approximately 1536 x 1792 pixels, with the character filling the frame in the same proportions and framing as image 1. It must look like precisely the same character when placed beside the original in-app poses.
Invariants: same front-facing slate/periwinkle-blue fox-like creature, same large pointed ears and pale pink inner ears, same asymmetric swept three-tuft hair silhouette, same violet/pink brow markings and thick dark brows, same wide amber eyes looking directly at the viewer, same short rounded muzzle and black rounded triangular nose, pale cheek fur, tiny muzzle freckles, same friendly open smile with small pointed teeth and visible tongue, same head/body proportions and facial geometry. Same navy hoodie with cyan zipper/lapel trim, orange neckerchief with the same folds, pale undershirt and tiny gold buttons, small violet outlined downward triangle badge on viewer-left chest. Same waist-up pose with BOTH open palms extended toward the viewer at the bottom, same rounded fingers, hand positions, sleeve folds and camera angle. Keep the existing soft stylized 3D render, lighting direction and colors. Add only faithful sharp detail, not new features.
Backdrop: completely plain perfectly flat chroma-key green #00FF00, including between fingers and beside the silhouette; no shadows or gradients on the green backdrop. This green is absent from the character. Finish torso below the hands so the final cutout can have a soft bottom fade.
Constraints: no wings, no extra fingers, no accessories, no background scene, no props, no text, no letters, no logo, no watermark. The tiny triangle clothing badge is a geometric marking, not a logo to invent.
Restoration priority: meticulous reference fidelity across the entire figure. Reconstruct small details at higher sampling resolution while preserving the original smooth stylized game-character rendering, original smile and relaxed welcoming hands.
```


## Verification and limits

Inspected the original cut-out, mockup, raw renders, and final dark-background comparison. Checked the final PNG dimensions, RGBA mode, fully transparent background, opaque interior, and transparent bottom row. Checked cut-outs against a light background as an edge review.

No application code changed. No app test suite, browser integration, provider voice call, or real-child session ran. Nothing was deployed. The lead owns selection and integration.
