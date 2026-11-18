# Parallel Image Search, live comparison 2026-11-18

Same scripted page body (one `<ot-image query>` slot, phone pane 370×610) under
`SCREEN_IMAGES=commons` and `commons+parallel`. Real Parallel fast search, real
Commons, real bounded downloads, real vision review (Muse Spark, Go, minimal),
real shell render. `compare.py` streams the page so the prefetch pool resolves
the slot while "writing", as in production. `combined-retry1` under colosseum
is a rerun of the combined job (see row 3).

| # | Ask | commons | commons+parallel |
|---|---|---|---|
| 1 | Portrait of Gustav II Adolf (16 Nov failure) | accepted Commons `File:Gustav II Adolf of Sweden.jpg` (search 0.21 s, image 4.75 s, job 8.35 s) | accepted same Commons file first (0.11 s, image 5.85 s, job 8.54 s) |
| 2 | Portrait of Gustav Vasa | accepted Commons `File:Gustav Vasa.jpg` (0.08 s, 2.45 s, 8.12 s) | accepted same Commons file first (0.10 s, 3.76 s, 8.73 s) |
| 3 | Colosseum | accepted Commons exterior photo (0.16 s, 3.28 s, 9.00 s) | first run: text fallback — a ~15 s review hit the job budget (provider variance); retry: accepted same Commons photo (0.29 s, 6.64 s, 9.98 s) |
| 4 | Flower (yellow dandelion in bloom) | all 3 Commons candidates correctly rejected (butterfly, B&W seed head, seed ball), text fallback (15.30 s, 17.82 s) | same 3 Commons rejections; Parallel candidates never reached before the budget ran out; text fallback (15.30 s, 17.79 s) |
| 5 | Water-cycle illustration | Commons: no candidates, text fallback (job 6.18 s) | **accepted Parallel**: Swedish USGS illustration `water-cycle-schools...` from `d9-wret.s3.us-west-2.amazonaws.com`, credit `Källa: www.usgs.gov` (search 0.92 s, image 8.43 s, job 12.21 s) |
| 6 | Map-like historical picture (Roman Empire) | accepted Commons `Roman empire at its greatest extent.JPG` (0.11 s, 2.76 s, 8.25 s) | accepted same Commons file first (0.11 s, 4.44 s, 7.42 s) |

What this says:

- The 16 Nov king-portrait failure is gone on both modes: Commons serves JPEG
  thumbnails since the `thumbmime` fix, and the review accepts them.
- Parallel fast search answers in ~1 s and its downloads pass the SSRF guard on
  real arbitrary hosts (S3, USGS). No CSP change: images ship as remote `https:`
  URLs, which `img-src data: https:` already allows.
- Parallel wins where Commons has nothing (row 5, accepted after Commons came
  back empty). Where Commons has a good picture, Commons is reviewed first and
  wins, so Parallel costs about one extra search (~1 s, overlapped) and nothing
  else: no Parallel download or review happens.
- Budget caveat: a slot gets ~17 s of search + download + review. Six sequential
  vision reviews do not fit when both sources return full candidate lists and the
  provider is slow (rows 3–4). The page still ships with a text fallback; nothing
  fails. Review concurrency is the follow-up if this bites in real lessons.
- Parallel returns plain-`http` file URLs often; they are upgraded to `https`
  before download and refused if the host does not serve valid TLS.
- No Parallel cool-down triggered in any run; no credits/quota errors. The
  402/429/5xx paths are covered by unit tests with recorded responses.

Per-ask folders hold `body.html`, `shot.png`, `images.json` (per-image source,
query, search latency, verdict, reason) and `row.json`; the page/patch
`meta.json` under each run gains the same in its `images` section.
