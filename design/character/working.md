# Working pose

The built-in image generation tool created `working.png` on 2026-11-11 from `web/public/character/thinking.webp`.
The app uses `web/public/character/working.webp`, exported at 900px high with WebP quality 88 and its alpha channel preserved.

Generation prompt:

> Use case: identity-preserve. Asset type: transparent character sprite for a live children's voice tutor web app. Use the attached image as the exact character identity and rendering-style reference. Create a new WORKING / DRAWING pose of this same friendly blue-purple fox named Räven: same swept purple quiff, big amber eyes, cream muzzle and chest, pink inner ears, dark navy zip hoodie with cyan edging, warm orange neckerchief, same cute polished soft 3D illustration style and proportions. Waist-up portrait cutout, full ears and head and elbows visible, no background at all, true transparent alpha. Fox is holding a small cream sketchpad in the left paw and actively drawing on it with a pencil in the right paw, with focused eyes looking down at the page and a tiny happy concentrated smile, shoulders turned slightly toward viewer LEFT where the teaching board sits. The pose must clearly communicate doing work, different from hand-on-chin thinking or speaking or listening. Sketchpad held naturally at chest height; paws and pencil anatomy clean and believable. Keep the character visually almost identical to the reference, not redesigned. Clean silhouette with a little padding around ears and elbows. No desk, no floor, no scene, no lettering, no labels, no UI, no watermark, no thought bubbles. Do not replicate the reference image's background or rectangular edge artifacts. Output a single portrait sprite.

Export command:

```sh
magick design/character/working.png -resize x900 -quality 88 web/public/character/working.webp
```
