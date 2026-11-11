"""Board surface regression check: generated HTML board fits, has no outer chrome, renders singly.

Covers two reported faults:
1. The generated board is clipped / wrong dimensions and shows as a "board in a
   board" with an unwanted outer headline. Root cause: the tutor commissions the
   board for the measured pane (board_w x board_h) but the browser shows it in a
   fixed-height iframe with an outer <h2>, padding and frame.
2. The equation renders twice (unstyled MathML next to HTML) because the iframe
   CSP blocks the KaTeX stylesheet (style-src) and fonts (font-src).

The check runs the real commission path (open_tutor.agent.Tutor) to learn what
the agent publishes, then pushes that payload through the real React app
(e2e build with the test-only LiveKit transport, same as mobile_probe.py) and
measures the actual iframe: no outer headline, no overflow, single equation,
loaded KaTeX font, loaded map tile, and — the genuine fit check — the entire
frame inside the visible .ot-board-scroll pane on desktop and phone, including
after a window resize/orientation change.

Sizes are never hand-coded: each viewport measures its own live
.ot-board-scroll content box, sends the placeholder first (production order),
and commissions at the settled teaching-pane size from the real browser ack —
returned to the real Tutor commission path through the fake participant, so
the settled-size handshake is exercised, not stubbed. A stale (arrival-width)
measurement fails the fit check instead of passing against an unrelated fixture.

Run from the repo root:
    uv run --project server --with playwright python web/e2e/board_render_check.py
Primary views: desktop landscape (1366x768) and phone portrait (390x844).
The resized screenshots are additional checks, not the primary evidence.
No providers, production endpoints, microphone or camera hardware are used.
"""
import asyncio
import concurrent.futures
import functools
import http.server
import json
import pathlib
import re
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

from playwright.sync_api import sync_playwright

OUT = ROOT / ".review-checks/board-render"
OUT.mkdir(parents=True, exist_ok=True)

results: list[dict] = []


def check(name: str, value: bool) -> bool:
    results.append({"check": name, "pass": bool(value)})
    print(("PASS " if value else "FAIL ") + name)
    return bool(value)


def read_csp() -> str:
    text = (ROOT / "web/src/components/Cards.tsx").read_text()
    m = re.search(r'const HTML_CSP\s*=\s*"([^"]+)"', text)
    assert m, "HTML_CSP literal not found in Cards.tsx"
    return m.group(1)


# ---- Part A: what the tutor publishes -------------------------------------------

import open_tutor.board_model as board_model  # noqa: E402
from open_tutor.agent import Tutor  # noqa: E402 (main thread: LiveKit plugins require it)


class FakeParticipant:
    """Stands in for the browser on the server side of the commission path.

    show_ack is the real browser pending acknowledgement captured earlier in
    the test (post-transition teaching size); returning it here drives the
    real Tutor._rpc settled-size consumption path, exactly as in production.
    """

    def __init__(self, show_ack: str = '{"ok":true}') -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.show_ack = show_ack

    async def perform_rpc(self, *, destination_identity, method, payload, response_timeout):
        self.calls.append((destination_identity, method, json.loads(payload)))
        if method == "board.show":
            return self.show_ack
        return '{"ok":true}'

    async def set_attributes(self, attributes):
        pass


class FakeRoom:
    def __init__(self, show_ack: str = '{"ok":true}') -> None:
        self.local_participant = FakeParticipant(show_ack)


def make_board_html(w: int, h: int) -> str:
    # A stand-in for a commissioned board: fixed-pixel content laid out for
    # exactly w x h (what the board model produces for the commissioned pane),
    # a KaTeX equation rendered the documented way, a map tile, a bottom
    # marker, a bottom-right corner marker, and small interactive controls.
    # The sandboxed frame (opaque origin) self-measures and postMessages the
    # metrics out: the parent page cannot inspect iframe internals, exactly
    # like the shipped app cannot.
    # Fixed chrome above the fold (~250px): title, equation, controls, tile.
    # The spacer pushes the bottom marker + corner to exactly the design
    # bottom so the whole document is h px tall with nothing below the fold.
    head = max(0, h - 300)
    return f"""<!doctype html><html><head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/jsxgraph@1.11.0/distrib/jsxgraphcore.js"></script>
<style>html,body{{margin:0;padding:0}}body{{margin:0;background:#181B22;color:#fff;font:20px sans-serif;position:relative;height:{h}px;overflow:hidden}}</style>
</head><body>
<h1 style="margin:0 0 8px;">Linj&auml;r ekvation</h1>
<div id="eq"></div>
<div style="margin:8px 0;display:flex;gap:8px;align-items:center;">
<button id="tryck" type="button" style="font-size:18px;padding:8px 16px;">Tryck</button>
<input id="svar" aria-label="svar" style="font-size:18px;padding:8px;" placeholder="skriv">
<span id="click-result" aria-live="polite"></span>
</div>
<img id="tile" src="https://tile.openstreetmap.org/0/0/0.png" width="64" height="64" alt="karta">
<div style="height:{head}px"></div>
<div id="bottom-marker">SLUT</div>
<div id="graph-probe" style="position:absolute;left:96px;top:180px;width:180px;height:110px"></div>
<div id="corner-marker" style="position:absolute;right:8px;bottom:8px;background:#22d3ee;color:#062a31;padding:4px 10px;border-radius:8px;font-size:16px;">H&Ouml;RN</div>
<script>
// Default KaTeX output (htmlAndMathml), as the reported board contained: the
// model does not always pass output:'html', so the frame must hide the
// MathML annotation via the stylesheet in either case.
katex.render("y=kx+m",document.getElementById("eq"),{{throwOnError:false}});
var graphProbe = JXG.JSXGraph.initBoard('graph-probe', {{boundingbox: [-2, 6, 4, -2], axis:false, grid:false, showNavigation:false, showCopyright:false}});
var probeCurve = graphProbe.create('functiongraph', [function(x){{ return 2*x+1; }}], {{strokeColor:'#22d3ee', strokeWidth:3}});
var probeLabel = graphProbe.create('text', [0, 1, 'label'], {{fontSize:18}});
graphProbe.update();
document.getElementById("tryck").addEventListener("click", function() {{
  document.getElementById("click-result").textContent = "klickad";
  parent.postMessage({{type:"board-interaction", clicked:true}}, "*");
}});
document.getElementById("svar").addEventListener("input", function(e) {{
  parent.postMessage({{type:"board-interaction", value:e.target.value}}, "*");
}});
function rect(el) {{
  var r = el.getBoundingClientRect();
  return {{x:r.x, y:r.y, top:r.top, bottom:r.bottom, left:r.left, right:r.right, width:r.width, height:r.height}};
}}
function report() {{
  var mathml = document.querySelector(".katex-mathml");
  var glyphs = document.querySelector(".katex-html");
  var marker = document.querySelector("#bottom-marker").getBoundingClientRect();
  var tile = document.querySelector("#tile");
  var faces = [];
  try {{ document.fonts.forEach(function(f) {{ faces.push(f.family + ":" + f.status); }}); }} catch (e) {{}}
  parent.postMessage({{type:"board-metrics",
    documentMode: document.compatMode,
    graphCurveWidth: probeCurve.rendNode.getBBox().width,
    graphCurveHeight: probeCurve.rendNode.getBBox().height,
    graphLabel: probeLabel.rendNode.textContent,
    scrollW: document.documentElement.scrollWidth, clientW: document.documentElement.clientWidth,
    scrollH: document.documentElement.scrollHeight, clientH: document.documentElement.clientHeight,
    innerW: window.innerWidth, innerH: window.innerHeight,
    markerBottomInFrame: marker.bottom <= window.innerHeight + 1,
    markerRect: rect(document.querySelector("#bottom-marker")),
    cornerRect: rect(document.querySelector("#corner-marker")),
    mathmlPosition: mathml && getComputedStyle(mathml).position,
    mathmlBoxW: mathml ? mathml.getBoundingClientRect().width : -1,
    glyphsBoxW: glyphs ? glyphs.getBoundingClientRect().width : -1,
    katexFont: faces.indexOf("KaTeX_Main:loaded") >= 0,
    tileW: tile.naturalWidth}}, "*");
}}
var tile = document.querySelector("#tile");
Promise.all([document.fonts.ready, (tile.decode ? tile.decode() : Promise.resolve()).catch(function(){{}})])
  .then(report);
setTimeout(report, 6000);
</script>
</body></html>"""


def commission_sync(w: int, h: int, device: str, show_ack: str) -> dict:
    """Run the async commission path from inside the sync Playwright driver."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(commission_at(w, h, device, show_ack))).result()


async def commission_at(w: int, h: int, device: str, show_ack: str) -> dict:
    room = FakeRoom(show_ack)
    tutor = Tutor({"name": "Leo", "grade": 7}, room, board={"w": w, "h": h, "device": device})
    tutor.child_identity = "learner-1"
    confirmed = json.loads(show_ack)["board"]
    html = make_board_html(confirmed["w"], confirmed["h"])

    async def fake_render(need, background, learner_name="", **kw):
        assert (kw["board_w"], kw["board_h"]) == (confirmed["w"], confirmed["h"]), f"model got {kw}, settled pane is {confirmed}"
        return {"html": html, "note": "Linjen y=kx+m.", "png": None}

    async def noseen(*a, **k):
        pass

    board_model.render_board, real = fake_render, board_model.render_board
    tutor.add_board_seen, real_seen = noseen, tutor.add_board_seen
    try:
        result = await tutor.commission_board(None, need="Visa linjen y=kx+m", background="Leo.")
    finally:
        board_model.render_board = real
        tutor.add_board_seen = real_seen
    assert "on screen now" in result, result
    by_method = {m: p for _, m, p in room.local_participant.calls}
    return {"pending": by_method["board.show"], "html": by_method["board.update"]}


# ---- Part B: the real app ------------------------------------------------------

MEASURE_SURFACE = """() => {
  const scroller = document.querySelector('.ot-board-scroll');
  if (!scroller) return null;
  const style = getComputedStyle(scroller);
  const padX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  const padY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  const r = scroller.getBoundingClientRect();
  const w = Math.round(scroller.clientWidth - padX);
  const h = Math.round(scroller.clientHeight - padY);
  const device = window.matchMedia(
    '(max-width: 600px), (max-width: 950px) and (max-height: 500px) and (pointer: coarse)'
  ).matches ? 'mobile' : 'desktop';
  return { w, h, device, rect: { top: r.top, bottom: r.bottom, left: r.left, right: r.right } };
}"""


def frame_metrics(page) -> dict:
    m = page.evaluate("window.__boardMetrics");
    frame_h = page.evaluate(
        "() => document.querySelector('.ot-html-frame').getBoundingClientRect().height"
    )
    return {
        "frameFitsPane": page.evaluate("""() => {
          const frame = document.querySelector('.ot-html-frame').getBoundingClientRect();
          const pane = document.querySelector('.ot-board-scroll').getBoundingClientRect();
          return frame.top >= pane.top - 1 && frame.bottom <= pane.bottom + 1
            && frame.left >= pane.left - 1 && frame.right <= pane.right + 1;
        }"""),
        # The bottom-right teaching marker must land on the visible surface,
        # not merely inside the iframe document: map its design position
        # through the fit-wrapper scale into page pixels and test the pane.
        "cornerOnPane": page.evaluate("""() => {
          const fit = document.querySelector('.ot-html-fit');
          const frame = document.querySelector('.ot-html-frame').getBoundingClientRect();
          const pane = document.querySelector('.ot-board-scroll').getBoundingClientRect();
          const m = window.__boardMetrics;
          if (!m || !m.cornerRect) return false;
          const scale = fit ? parseFloat(fit.dataset.scale || '1') : 1;
          // cornerRect is in iframe design pixels; the iframe viewport shows
          // the design box 1:1, so scale maps it to page pixels.
          const x = frame.left + m.cornerRect.left * scale;
          const y = frame.top + m.cornerRect.top * scale;
          const w = m.cornerRect.width * scale, h = m.cornerRect.height * scale;
          return x >= pane.left - 1 && y >= pane.top - 1
            && x + w <= pane.right + 1 && y + h <= pane.bottom + 1;
        }"""),
        "pendingFitsPane": page.evaluate("""() => {
          const card = document.querySelector('article[data-board-id]');
          const pane = document.querySelector('.ot-board-scroll').getBoundingClientRect();
          if (!card) return false;
          const r = card.getBoundingClientRect();
          return r.top >= pane.top - 1 && r.bottom <= pane.bottom + 1
            && r.left >= pane.left - 1 && r.right <= pane.right + 1;
        }"""),
        "pageNoXOverflow": page.evaluate(
            "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
        ),
        "articleHasH2": page.evaluate("!!document.querySelector('article[data-board-id] h2')"),
        "articleLabel": page.evaluate(
            "document.querySelector('article[data-board-id]').getAttribute('aria-label')"
        ),
        "frameTitle": page.evaluate("document.querySelector('.ot-html-frame').getAttribute('title')"),
        "frameH": frame_h,
        **m,
    }


def last_board_size_event(page) -> dict | None:
    return page.evaluate("""() => {
      const events = (window.mobileProbe && window.mobileProbe.events) || [];
      for (let i = events.length - 1; i >= 0; i--) {
        const [kind, text, opts] = events[i];
        if (kind !== 'text' || !opts || opts.topic !== 'session-event') continue;
        try {
          const data = JSON.parse(text);
          if (data && data.type === 'board-size') return data;
        } catch {}
      }
      return null;
    }""")


def run_browser(csp: str) -> None:
    subprocess.run(
        ["npm", "exec", "--", "vite", "build", "--config", "e2e/vite.config.mjs"],
        cwd=ROOT / "web",
        check=True,
        stdout=subprocess.DEVNULL,
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / ".review-checks/mobile-site"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:" + str(server.server_port)
    try:
        with sync_playwright() as p:
            shells = sorted(
                pathlib.Path.home().glob(
                    ".cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
                )
            )
            browser = p.chromium.launch(executable_path=str(shells[-1]) if shells else None)
            for vw, vh, label, resize_to in [
                (1366, 768, "desktop", {"width": 1024, "height": 600}),
                (390, 844, "phone", {"width": 844, "height": 390}),
            ]:
                phone = label == "phone"
                ctx = browser.new_context(
                    viewport={"width": vw, "height": vh}, is_mobile=phone, has_touch=phone
                )
                page = ctx.new_page()
                page.route(
                    "**/api/session",
                    lambda route: route.fulfill(
                        json={"url": "ws://fictional.invalid", "token": "fictional", "room": "room"}
                    ),
                )
                page.goto(url)
                page.get_by_label("Förnamn", exact=True).fill("Leo")
                page.get_by_role("button", name="Starta", exact=True).click()
                page.locator(".ot-bottombar").wait_for()
                page.locator(".ot-board-scroll").wait_for()

                def rpc(method, data):
                    return page.evaluate(
                        "async ([m, d]) => await mobileProbe.rooms.at(-1).rpc.get(m)"
                        "({payload: JSON.stringify(d)})",
                        [method, data],
                    )

                page.evaluate(
                    """if (!window.__boardMetricsHook) {
                      window.__boardMetricsHook = true;
                      window.addEventListener('message', (e) => {
                        if (!e.data) return;
                        if (e.data.type === 'board-metrics') window.__boardMetrics = e.data;
                        if (e.data.type === 'board-interaction') {
                          window.__boardInteraction = e.data;
                          if (e.data.clicked) window.__boardClicked = true;
                          if (e.data.value !== undefined) window.__boardInputValue = e.data.value;
                        }
                      });
                    }"""
                )
                # The live surface, measured in the running app — never hand-coded.
                page.wait_for_timeout(900)  # debounce + ResizeObserver board-size report
                arrival = page.evaluate(MEASURE_SURFACE)
                check(f"{label}: live board surface is measurable", bool(arrival) and arrival["w"] >= 1 and arrival["h"] >= 1)
                reported = last_board_size_event(page)
                check(
                    f"{label}: app reports the real surface over board-size transport",
                    bool(reported)
                    and abs(reported["w"] - arrival["w"]) <= 2
                    and abs(reported["h"] - arrival["h"]) <= 2
                    and reported["device"] == arrival["device"],
                )
                # First pending -> teaching transition, in production order:
                # the placeholder goes out before commissioning, and its ack
                # carries the settled teaching-pane size the tutor freezes
                # the board design to (not the narrower arrival pane).
                show_ack_raw = rpc(
                    "board.show",
                    {"id": "b1", "kind": "pending", "title": "Ritar…", "height": arrival["h"]},
                )
                show_ack = json.loads(show_ack_raw)
                check(f"{label}: pending acknowledged", show_ack.get("ok") is True)
                check(
                    f"{label}: pending ack carries the settled board size",
                    isinstance(show_ack.get("board"), dict)
                    and show_ack["board"].get("w", 0) >= 1
                    and show_ack["board"].get("h", 0) >= 1,
                )
                page.wait_for_selector("main.ot-main-teaching", timeout=5000)
                check(f"{label}: first pending switches arrival to teaching", True)
                # The ack must describe the post-transition pane, not arrival.
                settled = page.evaluate(MEASURE_SURFACE)
                confirmed = show_ack["board"]
                check(
                    f"{label}: pending ack matches the live teaching pane",
                    abs(confirmed["w"] - settled["w"]) <= 2
                    and abs(confirmed["h"] - settled["h"]) <= 2
                    and confirmed.get("device") == settled["device"],
                )
                if label == "desktop":
                    check(
                        f"{label}: teaching pane is wider than arrival "
                        f"({arrival['w']}->{settled['w']})",
                        settled["w"] > arrival["w"],
                    )
                    check(
                        f"{label}: teaching pane keeps arrival height",
                        settled["h"] == arrival["h"],
                    )

                # Commission through the real Tutor path at the confirmed
                # size; the fake returns the real browser ack so _rpc freezes
                # the design to the settled pane. The model stub lays out
                # fixed pixels for exactly that size.
                payload = commission_sync(arrival["w"], arrival["h"], arrival["device"], show_ack_raw)
                check(
                    f"agent {label}: placeholder starts at arrival pane height",
                    payload["pending"].get("height") == arrival["h"],
                )
                check(
                    f"agent {label}: html frame size matches confirmed pane "
                    f"({confirmed['w']}x{confirmed['h']})",
                    payload["html"].get("height") == confirmed["h"]
                    and payload["html"].get("width") == confirmed["w"],
                )
                check(
                    f"agent {label}: placeholder replaced in place",
                    payload["pending"]["id"] == payload["html"]["id"],
                )
                if label == "desktop":
                    check(
                        f"agent {label}: design uses the teaching width, not arrival "
                        f"({arrival['w']}->{payload['html']['width']})",
                        payload["html"]["width"] == settled["w"] > arrival["w"],
                    )
                page.wait_for_timeout(400)  # fit clamp + avatar pose settle
                pending_fits = page.evaluate("""() => {
                  const card = document.querySelector('article[data-board-id]');
                  const pane = document.querySelector('.ot-board-scroll').getBoundingClientRect();
                  if (!card) return false;
                  const r = card.getBoundingClientRect();
                  return r.top >= pane.top - 1 && r.bottom <= pane.bottom + 1
                    && r.left >= pane.left - 1 && r.right <= pane.right + 1;
                }""")
                check(f"{label}: pending fits the visible surface", pending_fits)
                check(f"{label}: pending has no outer headline", not page.locator('article[data-board-id] h2').count())
                fox = page.evaluate("""() => {
                  const img = document.querySelector('.ot-avatar-img');
                  if (!img) return { src: null, visible: false };
                  const r = img.getBoundingClientRect();
                  const vw = window.innerWidth, vh = window.innerHeight;
                  return {
                    src: img.currentSrc || img.src,
                    visible: r.width > 40 && r.height > 40
                      && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw,
                  };
                }""")
                check(f"{label}: working fox visible while drawing", "working" in (fox["src"] or "") and fox["visible"])
                page.screenshot(path=str(OUT / f"board-{label}-pending.png"))

                page.evaluate("window.__boardMetrics = null; window.__boardInteraction = null; window.__boardClicked = null; window.__boardInputValue = null;")
                update_ack = json.loads(rpc("board.update", payload["html"]))
                check(f"{label}: html acknowledged", update_ack.get("ok") is True)
                check(
                    f"{label}: update ack carries the board size",
                    isinstance(update_ack.get("board"), dict)
                    and update_ack["board"].get("w", 0) >= 1
                    and update_ack["board"].get("h", 0) >= 1,
                )
                # Desktop: the drawing uses the full available width and the
                # same height; portrait phone: exactly the phone pane dims.
                taught = page.evaluate(MEASURE_SURFACE)
                check(
                    f"{label}: commissioned drawing matches the live pane exactly",
                    payload["html"]["width"] == taught["w"]
                    and payload["html"]["height"] == taught["h"],
                )
                try:
                    page.wait_for_function("window.__boardMetrics !== null", timeout=15000)
                except Exception:
                    pass  # recorded as failed checks below instead of hanging
                m = frame_metrics(page)
                check(f"{label}: entire frame fits the visible board pane", m["frameFitsPane"])
                check(f"{label}: board uses standards mode like tutor screenshot", m["documentMode"] == "CSS1Compat")
                check(f"{label}: no outer headline on generated board", not m["articleHasH2"])
                check(f"{label}: accessible title kept", bool(m["articleLabel"]) and bool(m["frameTitle"]))
                check(f"{label}: no horizontal overflow", m["scrollW"] <= m["clientW"] + 1)
                check(
                    f"{label}: no vertical clipping (frame {m['frameH']:.0f}px fits content)",
                    m["scrollH"] <= m["clientH"] + 1 and m["markerBottomInFrame"],
                )
                check(f"{label}: bottom-right marker on the visible pane", m["cornerOnPane"])
                check(f"{label}: no page-level horizontal clipping", m["pageNoXOverflow"])
                check(f"{label}: KaTeX stylesheet applied (mathml hidden)", m["mathmlPosition"] == "absolute")
                check(
                    f"{label}: equation rendered once (annotation hidden, glyphs visible)",
                    m["mathmlBoxW"] <= 2 and m["glyphsBoxW"] > 50,
                )
                check(f"{label}: KaTeX font loaded", m["katexFont"])
                check(f"{label}: JSXGraph function curve is actually drawn", m["graphCurveWidth"] > 10 and m["graphCurveHeight"] > 10)
                check(f"{label}: JSXGraph documented text signature renders", m["graphLabel"] == "label")
                check(f"{label}: map tile loaded (img-src allowance)", m["tileW"] > 0)
                # Interactivity survives the fit scaling: drive the real frame.
                try:
                    frame = page.frame_locator(".ot-html-frame")
                    frame.locator("#tryck").click(timeout=5000)
                    frame.locator("#svar").fill("42", timeout=5000)
                    page.wait_for_function("window.__boardClicked === true", timeout=5000)
                    page.wait_for_function("window.__boardInputValue === '42'", timeout=5000)
                    clicked = page.evaluate("window.__boardClicked === true")
                    typed = page.evaluate("window.__boardInputValue")
                except Exception:
                    clicked, typed = False, None
                check(f"{label}: board stays interactive after scaling", clicked is True and typed == "42")
                page.screenshot(path=str(OUT / f"board-{label}.png"))

                # Resize / orientation after the finished board: the same
                # commissioned pixels must still fit the new visible pane.
                page.evaluate("window.__boardInteraction = null; window.__boardClicked = null; window.__boardInputValue = null;")
                page.set_viewport_size(resize_to)
                page.wait_for_timeout(1200)  # ResizeObserver + debounce + scale recompute
                # The iframe document keeps its design size; the wrapper fits it.
                r2 = frame_metrics(page)
                check(f"{label}: resized frame still fits the visible pane", r2["frameFitsPane"])
                check(f"{label}: resized bottom-right marker still on pane", r2["cornerOnPane"])
                check(
                    f"{label}: resized board keeps content unclipped",
                    r2["scrollW"] <= r2["clientW"] + 1
                    and r2["scrollH"] <= r2["clientH"] + 1
                    and r2["markerBottomInFrame"],
                )
                check(f"{label}: resized page has no horizontal clipping", r2["pageNoXOverflow"])
                try:
                    frame2 = page.frame_locator(".ot-html-frame")
                    frame2.locator("#tryck").click(timeout=5000)
                    page.wait_for_function(
                        "window.__boardInteraction && window.__boardInteraction.clicked", timeout=5000
                    )
                    clicked2 = True
                except Exception:
                    clicked2 = False
                check(f"{label}: resized board stays interactive", clicked2 is True)
                page.screenshot(path=str(OUT / f"board-{label}-resized.png"))
                ctx.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    csp = read_csp()
    print("served CSP:", csp)
    check("CSP allows CDN stylesheets", "style-src 'unsafe-inline' https://cdn.jsdelivr.net" in csp)
    check("CSP allows CDN fonts", "font-src https://cdn.jsdelivr.net" in csp)

    run_browser(csp)
    (OUT / "report.json").write_text(json.dumps({"checks": results, "csp": csp}, indent=2))
    failed = [r["check"] for r in results if not r["pass"]]
    print(f"{len(results) - len(failed)}/{len(results)} board checks passed")
    if failed:
        raise SystemExit("FAILED: " + "; ".join(failed))


if __name__ == "__main__":
    main()
