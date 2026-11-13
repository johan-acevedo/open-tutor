"""Real-provider browser+voice probe for the material library (step 4e).

A fictional learner joins the REAL preview deployment in a REAL Chromium
(build app, real LiveKit Cloud room, real Soniox STT, real Muse Go tutor,
real Deepgram TTS, real rendered MaterialSection) and speaks with a
synthetic Swedish voice fed through Chromium's fake microphone file.
Nothing is mocked: the probe never calls search_materials/show_material
itself -- only the tutor model can, after hearing the learner.

Run (from the repo root; spends a little on existing provider keys):
    OPEN_TUTOR_ENV=~/.config/open-tutor-materials/env \
      server/bin/with-env \
      ~/.local/share/open-tutor/materials/preview-venv/bin/python \
      web/e2e/material_voice_probe.py \
      --url https://elitebook.tail2e1c4e.ts.net:9443/ --name Pax

Output (outside git): report.json, timeline.jsonl, captions, screenshots,
thesynthetic tape + clips, fetched section HTML/metadata. No tokens or keys.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "server"
sys.path.insert(0, str(SERVER))

URL_DEFAULT = "https://elitebook.tail2e1c4e.ts.net:9443/"
FFMPEG = Path.home() / ".cache/ms-playwright/ffmpeg-1011/ffmpeg-linux"

# Fictional learner lines (synthetic speech, clearly labelled everywhere).
U1 = ("Hej! Jag heter Pax och jag läser fysik om elektriska kretsar. "
      "Kan du söka i skolboken efter hur en sluten krets med batteri och lampa fungerar, "
      "visa sidan här och förklara bilden för mig?")
U2 = ("Tack! Kan du också visa ett räkneexempel med ekvationer ur matteboken, "
      "och förklara stegen?")
U1_AT, U2_AT, TAPE_END = 45.0, 330.0, 540.0  # seconds


def log(out: Path, kind: str, **data) -> dict:
    entry = {"t": round(time.monotonic() - log.t0, 2), "event": kind, **data}
    with (out / "timeline.jsonl").open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False)[:220], flush=True)
    return entry


log.t0 = time.monotonic()


async def synth_clip(text: str, dest: Path) -> tuple[bytes, int]:
    """Synthesize one Swedish learner clip with the existing Deepgram adapter."""
    from livekit.agents.utils import http_context
    from open_tutor.deepgram_tts import DeepgramFluxTTS

    async with http_context.open():
        tts = DeepgramFluxTTS(api_key=os.environ.get("DEEPGRAM_API_KEY") or None)
        stream = tts.synthesize(text)
        frame = await stream.collect()
    raw = bytes(frame.data)
    dest.write_bytes(raw)
    return raw, frame.sample_rate


def write_wav(path: Path, pcm: bytes, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def build_tape(clips: list[tuple[Path, float]], total: float, dest: Path) -> None:
    """Assemble the 48 kHz mic tape: silence with clips at fixed offsets."""
    rate = 48000
    tape = bytearray(int(total * rate) * 2)
    for clip_path, at in clips:
        with wave.open(str(clip_path)) as w:
            assert w.getnchannels() == 1 and w.getsampwidth() == 2
            pcm, src_rate = w.readframes(w.getnframes()), w.getframerate()
        if src_rate != rate:  # linear upsample
            import array

            src = array.array("h", pcm)
            n = int(len(src) * rate / src_rate)
            dst = array.array("h", bytes(n * 2))
            for i in range(n):
                pos = i * len(src) / n
                lo, frac = int(pos), pos - int(pos)
                hi = min(lo + 1, len(src) - 1)
                dst[i] = int(src[lo] * (1 - frac) + src[hi] * frac)
            pcm = dst.tobytes()
        off = int(at * rate) * 2
        tape[off:off + len(pcm)] = pcm[: len(tape) - off]
    write_wav(dest, bytes(tape), rate)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL_DEFAULT)
    ap.add_argument("--name", default="Pax")
    ap.add_argument("--grade", type=int, default=7)
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-synth", action="store_true",
                    help="reuse an existing tape.wav in --out instead of synthesizing")
    ap.add_argument("--session-budget", type=float, default=480.0)
    args = ap.parse_args()

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else (
        Path.home() / ".local/state/open-tutor/material-probe" / stamp)
    out.mkdir(parents=True, exist_ok=True)
    log.t0 = time.monotonic()

    from playwright.sync_api import sync_playwright

    # ---- readiness (no session content touched) ----
    import urllib.request

    health = json.loads(urllib.request.urlopen(
        args.url.rstrip("/") + "/api/health", timeout=15).read())
    load = Path("/proc/loadavg").read_text().split()[:3]
    log(out, "readiness", health=health, loadavg=load, url=args.url,
        learner=args.name, synthetic_voice=True, real_providers=True)
    if not (health.get("ok") and health.get("livekit")):
        raise SystemExit(f"preview not ready: {health}")

    # ---- synthetic learner tape ----
    tape = out / "tape.wav"
    if args.no_synth:
        if not tape.exists():
            raise SystemExit(f"--no-synth but no {tape}")
        log(out, "tape_reused", tape=str(tape))
    else:
        u1pcm, u1rate = asyncio.run(synth_clip(U1, out / "clip_u1_24k.pcm"))
        u2pcm, u2rate = asyncio.run(synth_clip(U2, out / "clip_u2_24k.pcm"))
        c1, c2 = out / "clip_u1.wav", out / "clip_u2.wav"
        write_wav(c1, u1pcm, u1rate)
        write_wav(c2, u2pcm, u2rate)
        build_tape([(c1, U1_AT), (c2, U2_AT)], TAPE_END, tape)
        log(out, "tape_built", tape=str(tape), u1_rate=u1rate, u2_rate=u2rate,
            u1_text=U1, u2_text=U2, synthetic_learner_speech=True)

    room_name: dict = {}
    captions: list[dict] = []
    samples: list[dict] = []

    with sync_playwright() as p:
        cached = sorted(Path.home().glob(
            ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
        browser = p.chromium.launch(
            executable_path=str(cached[-1]) if cached else None,
            args=["--use-fake-ui-for-media-stream",
                  "--use-fake-device-for-media-stream",
                  f"--use-file-for-fake-audio-capture={tape}",
                  "--autoplay-policy=no-user-gesture-required"],
        )
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  permissions=["microphone"],
                                  ignore_https_errors=True)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def on_response(resp):
            try:
                if resp.url.endswith("/api/session") and resp.ok:
                    data = resp.json()
                    room_name["room"] = data.get("room")  # token deliberately dropped
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        page.get_by_role("option", name="Ny här?").click()
        page.get_by_label("Förnamn", exact=True).fill(args.name)
        page.get_by_label("Årskurs", exact=True).select_option(str(args.grade))
        t_start = time.monotonic()
        page.get_by_role("button", name="Starta", exact=True).click()
        page.locator(".ot-mic-btn.live").wait_for(timeout=30000)
        log(out, "joined", room=room_name.get("room"), join_s=round(time.monotonic() - t_start, 1))
        page.screenshot(path=str(out / "joined.png"))

        page.evaluate("""() => {
          window.__probe = {setup: false, read: null};
          window.__probeTick = () => {
            try {
              if (!window.__probe.setup) {
                const el = document.querySelector('audio');
                if (!el || !el.srcObject) return -2;
                const AC = window.AudioContext || window.webkitAudioContext;
                const actx = new AC();
                const src = actx.createMediaStreamSource(el.srcObject);
                const an = actx.createAnalyser(); an.fftSize = 2048;
                src.connect(an);
                const buf = new Float32Array(an.fftSize);
                window.__probe.read = () => {
                  an.getFloatTimeDomainData(buf);
                  let s = 0;
                  for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
                  return Math.sqrt(s / buf.length);
                };
                window.__probe.setup = true;
              }
              return window.__probe.read();
            } catch (e) { return -1; }
          };
        }""")

        last_caption = ""
        material_first: float | None = None
        material_info: dict = {}
        deadline = time.monotonic() + args.session_budget
        explained_after_show = 0.0
        while time.monotonic() < deadline:
            poll_s = 2.0
            cap = ""
            try:
                cap = page.locator(".ot-caption").inner_text(timeout=2000) or ""
            except Exception:
                pass
            rms = page.evaluate("window.__probeTick()")
            frame = page.locator("iframe.ot-material-frame")
            has_frame = frame.count() > 0
            attrib = ""
            if page.locator(".ot-material-attrib").count():
                try:
                    attrib = page.locator(".ot-material-attrib").inner_text(timeout=1000)
                except Exception:
                    pass
            now = round(time.monotonic() - log.t0, 1)
            samples.append({"t": now, "rms": rms, "caption_len": len(cap),
                            "material": has_frame})
            if cap != last_caption:
                last_caption = cap
                captions.append({"t": now, "caption": cap})
                log(out, "caption", text=cap[:180])
            if has_frame and material_first is None:
                material_first = now
                src = frame.first.get_attribute("src") or ""
                m = re.search(r"/materials/sections/([^/]+)/index.html", src)
                material_info = {"src": src, "section_id": m.group(1) if m else None,
                                 "attribution": attrib}
                log(out, "material_shown", **material_info)
                page.screenshot(path=str(out / "material_shown.png"))
                try:
                    frame.first.scroll_into_view_if_needed(timeout=5000)
                    frame.first.screenshot(path=str(out / "material_frame.png"),
                                           timeout=15000)
                except Exception as exc:
                    log(out, "frame_screenshot_failed", error=str(exc)[:150])
            if material_first is not None:
                explained_after_show = now - material_first
                # Primary scenario proven: page shown + tutor kept explaining
                # afterwards (long, growing captions + audible audio).
                if explained_after_show > 150:
                    break
            time.sleep(poll_s)

        # ---- material fetch evidence (what the browser actually got) ----
        sid = material_info.get("section_id")
        fetched: dict = {}
        base = args.url.rstrip("/")
        if sid:
            try:
                meta_resp = page.request.get(
                    f"{base}/api/materials/sections/{sid}", timeout=15000)
                fetched["meta_status"] = meta_resp.status
                meta = meta_resp.json()
                fetched["meta_keys"] = sorted(meta.keys())
                fetched["title"] = meta.get("title")
                fetched["visible_image_count"] = meta.get("visible_image_count")
                fetched["attribution"] = meta.get("attribution")
                (out / "section_meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2))
            except Exception as exc:
                fetched["meta_error"] = str(exc)[:200]
            try:
                html_resp = page.request.get(
                    f"{base}/materials/sections/{sid}/index.html", timeout=15000)
                html = html_resp.text()
                (out / "section_page.html").write_text(html)
                fetched["html_bytes"] = len(html)
                fetched["has_marker"] = f'data-material-section="{sid}"' in html
                imgs = re.findall(r"<img[^>]+src=[\"']([^\"']+)", html)
                fetched["img_refs"] = len(imgs)
                fetched["img_unique"] = len(set(imgs))
                ok_imgs = 0
                for src_img in sorted(set(imgs))[:12]:
                    r = page.request.get(
                        f"{base}/materials/sections/{sid}/{src_img.lstrip('/')}",
                        timeout=15000)
                    if r.status == 200:
                        ok_imgs += 1
                        if ok_imgs <= 3:  # keep 3 real files for answer judging
                            (out / f"figure_{ok_imgs}{Path(src_img).suffix or '.img'}"
                             ).write_bytes(r.body())
                fetched["img_http_200"] = ok_imgs
            except Exception as exc:
                fetched["html_error"] = str(exc)[:200]
            log(out, "material_evidence", **fetched)

        audio_hit = [s for s in samples if isinstance(s["rms"], float) and s["rms"] > 0.01]
        log(out, "session_summary",
            room=room_name.get("room"),
            n_captions=len(captions),
            caption_chars=sum(len(c["caption"]) for c in captions),
            audio_samples=len(samples),
            audible_samples=len(audio_hit),
            max_rms=round(max([s["rms"] for s in samples
                               if isinstance(s["rms"], float)] or [0]), 4),
            material=material_info, fetched=fetched,
            browser_errors=errors)
        page.screenshot(path=str(out / "before_end.png"))

        # ---- end the session through the real UI ----
        try:
            page.get_by_role("button", name="Avsluta", exact=True).first.click(timeout=5000)
        except Exception:
            page.get_by_label("Avsluta sessionen").first.click(timeout=5000)
        try:
            page.get_by_role("button", name="Ja, avsluta", exact=True).click(timeout=8000)
        except Exception as exc:
            log(out, "no_end_confirm", note=str(exc)[:120])
        try:
            page.get_by_text(f"Bra jobbat idag, {args.name}!", exact=True).wait_for(timeout=60000)
            ended = True
        except Exception:
            ended = False
        log(out, "ended", clean_end_card=ended)
        page.screenshot(path=str(out / "ended.png"))
        (out / "captions.json").write_text(
            json.dumps(captions, ensure_ascii=False, indent=2))
        (out / "samples.json").write_text(json.dumps(samples))
        browser.close()

    report = {
        "url": args.url,
        "learner": {"name": args.name, "grade": args.grade, "fictional": True},
        "synthetic_learner_speech": True,
        "real_providers": {"stt": "soniox", "llm": "opencode-go/muse-spark",
                           "tts": "deepgram/flux-ludvig-sv"},
        "room": room_name.get("room"),
        "material": material_info,
        "fetched": fetched if sid else None,
        "captions": captions,
        "ended_cleanly": ended,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"OUT={out}")
    print(json.dumps({k: (v if k != "captions" else f"{len(v)} turns")
                      for k, v in report.items()}, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
