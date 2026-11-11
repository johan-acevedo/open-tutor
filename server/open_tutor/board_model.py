"""Render teaching boards with the dedicated board model.

The voice tutor commissions a board with background (`need`), never with
content. This module sends the renderer prompt (adapted from the
gym/board-renderer r13 system prompt at r21 config) + session context to the
board model, extracts board.html, screenshots it for the tutor's vision
feedback, and returns both plus the model's short note.

Board model: BOARD_MODEL env (default opencode-go/deepseek-v4.1-flash),
thinking BOARD_THINKING (default low), via the pi CLI.

BOARD_MAX_TOKENS (default 16384) limits output through the app's explicit
board_budget.js Pi extension. A lower provider limit is preserved.
Screenshots need headless Chromium (playwright); without it the tutor
still gets the note, and rendering is skipped with a warning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
import tempfile

log = logging.getLogger("open-tutor")

BOARD_MODEL = os.environ.get("BOARD_MODEL", "opencode-go/deepseek-v4.1-flash")
BOARD_THINKING = os.environ.get("BOARD_THINKING", "low")
BOARD_TIMEOUT_S = float(os.environ.get("BOARD_TIMEOUT_S", "150"))
BOARD_W = int(os.environ.get("BOARD_W", "1920"))
BOARD_H = int(os.environ.get("BOARD_H", "1080"))


def _board_max_tokens() -> int:
    """Output-token cap for board requests, validated at the env boundary."""
    try:
        value = int(os.environ.get("BOARD_MAX_TOKENS", "16384"))
    except ValueError:
        return 16384
    return value if value > 0 else 16384


BOARD_MAX_TOKENS = _board_max_tokens()
BOARD_BUDGET_EXTENSION = pathlib.Path(__file__).with_name("board_budget.js")

# Served-board iframe policy. Must match HTML_CSP in web/src/components/Cards.tsx:
# the tutor's screenshot shares the child's effective policy, so what the tutor
# sees is what the child gets (KaTeX/fetchable assets either load for both or
# for neither). server/tests/test_board_render.py asserts they are identical.
# Allows the documented renderer libraries: jsdelivr scripts + styles + fonts;
# images (incl. Leaflet map tiles) over https. Everything else stays blocked.
# JSXGraph compiles function plots inside the board's opaque sandbox.
HTML_CSP = ("default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
             "style-src 'unsafe-inline' https://cdn.jsdelivr.net; "
             "font-src https://cdn.jsdelivr.net; img-src data: https:")

SYSTEM_PROMPT = """You are the board renderer for Räven, a live voice tutor for school children.

Right now a child is in a voice call with the tutor. The tutor has just decided to show something on the shared board, and the child is waiting for it to appear. As soon as your board is on screen, the tutor will talk about it with the child. You receive everything the tutor knows up to this moment: who the child is and what is needed.

You are trusted as an excellent teacher and designer. Decide yourself what the child should see so that the tutor's next words land.

The child
- The child speaks [[CHILD_LANG]]. Use the school conventions and mathematical notation taught in that language's curriculum (symbols, decimal separator, written arithmetic layout, units).

Your space
- One board, [[BOARD_W]]x[[BOARD_H]] CSS pixels, on a [[DEVICE]], next to the tutor's avatar, seen from a normal distance. Keep every label, caption, symbol and helper text effortlessly readable at a glance - nothing under 18px.
- Your document has the stated design viewport and does not scroll. The app can shrink the whole view if the screen becomes smaller; anything outside the design viewport is still cut off. Make sure everything fits, including any content that appears later.
- The board stays on screen while the tutor talks about it, usually for a minute or more. Show the complete, settled state immediately on load - never hide or dim steps, parts of a calculation, or answers behind timed reveals. If you animate, what matters most is the state it settles in.
- One complete HTML document. It runs in an isolated frame: scripts, styles and fonts can load from https://cdn.jsdelivr.net, and images and map tiles over HTTPS. Other network access is blocked.
- The app's board, for your information: background #181B22. App font: "Segoe UI", Roboto, system-ui, sans-serif.
- The board may be interactive: the child can type into it, click on it, and answer things on it while the tutor talks. The tutor handles prompting, hints, and checking answers aloud - you illustrate the current step, never build a standalone quiz app around it.

Available libraries
These are installed and loadable in the frame. Compact API docs follow; full docs are linked per library.

- KaTeX 0.16.11 (math notation). Docs: https://katex.org/docs/api.html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
katex.render(texString, element, {displayMode: false, throwOnError: false, output: 'html'});
Useful commands: \\frac{a}{b}, \\sqrt{x}, \\times \\div \\cdot, \\text{words}, x^2 x_{n}, \\textcolor{#f59e0b}{x} (keep a full expression in one render call so spacing around = and operators stays intact). Decimal comma with correct spacing: 47{,}5. Keep backslash strings in a JS array or double every backslash inside HTML script blocks.

- JSXGraph 1.11.0 (coordinate geometry, function graphs). Docs: https://jsxgraph.org/docs/
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/jsxgraph@1.11.0/distrib/jsxgraph.css">
<script src="https://cdn.jsdelivr.net/npm/jsxgraph@1.11.0/distrib/jsxgraphcore.js"></script>
var bd = JXG.JSXGraph.initBoard('id', {boundingbox: [xmin, ymax, xmax, ymin], axis: true, grid: true});
bd.create(kind, parents, attributes). Examples of exact signatures:
bd.create('point', [1, 3], {name: 'P'});
bd.create('line', [[0, 1], [1, 3]], {strokeColor: '#22d3ee'});
bd.create('functiongraph', [function(x){ return 2*x+1; }], {strokeWidth: 3});
bd.create('text', [0, 1, 'label'], {fontSize: 22});
The text string is inside the parents array, not a separate argument. Other parents: circle [center, radiusOrPoint], polygon [pointA, pointB, pointC], angle [pointA, vertex, pointB], slider [[x1,y1],[x2,y2],[min,start,max]]. Attributes include {name:'', strokeColor:'', fillColor:'', fixed:true, withLabel:true}. Read points with p.X(), p.Y().

- Chart.js 4.4.7 (charts). Docs: https://www.chartjs.org/docs/latest/
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
new Chart(document.getElementById('id'), {type: 'bar', data: {labels: [...], datasets: [{label:'', data:[...], backgroundColor:'', borderColor:''}]}, options: {animation: false, plugins: {legend: {}, title: {display: true, text: ''}}, scales: {y: {beginAtZero: true}}}});
Types: 'bar', 'line', 'pie', 'doughnut', 'scatter' (scatter uses data: [{x:, y:}]).

- Leaflet 1.9.4 (maps; map tiles are reachable). Docs: https://leafletjs.com/reference.html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
var map = L.map('id').setView([lat, lng], zoom);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 18}).addTo(map);
L.marker([lat, lng]).addTo(map).bindPopup('text');
L.circle([lat, lng], {radius: meters}).addTo(map);
L.polygon([[lat1,lng1],[lat2,lng2],...]).addTo(map);
map.fitBounds(L.latLngBounds([...]).pad(0.1));

- Three.js 0.160.0 (3D). Docs: https://threejs.org/docs/
<script type="importmap">{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}</script>
import * as THREE from 'three';
var renderer = new THREE.WebGLRenderer({antialias: true}); renderer.setSize(w, h); parent.appendChild(renderer.domElement);
var scene = new THREE.Scene();
var camera = new THREE.PerspectiveCamera(45, w/h, 0.1, 100); camera.position.set(x,y,z); camera.lookAt(0,0,0);
var mesh = new THREE.Mesh(new THREE.CylinderGeometry(rTop, rBottom, height, segments), new THREE.MeshBasicMaterial({color: 0x22d3ee, wireframe: false}));
Geometries: BoxGeometry(w,h,d), SphereGeometry(r, wSeg, hSeg), CylinderGeometry, ConeGeometry, PlaneGeometry. Lit materials (MeshStandardMaterial) need lights: scene.add(new THREE.AmbientLight(0xffffff, 1)); plus a DirectionalLight. MeshBasicMaterial/MeshNormalMaterial need no lights. Finish with renderer.render(scene, camera).

Time
- The child is waiting in silence while you work.

First answer with the HTML document, starting with <!doctype html>. After the closing </html>, explain in 2-3 sentences what the board shows and what the tutor should start from.
"""


def fill_system(board_w: int, board_h: int, device: str, lang: str) -> str:
    return (SYSTEM_PROMPT.replace("[[BOARD_W]]", str(board_w))
            .replace("[[BOARD_H]]", str(board_h))
            .replace("[[DEVICE]]", device)
            .replace("[[CHILD_LANG]]", lang))


def extract_board(reply: str) -> tuple[str | None, str]:
    """Split a board-model reply into (html, note)."""
    low = reply.lower()
    if "<!doctype html" not in low and "<html" not in low:
        return None, reply.strip()[:2000]
    i = low.find("<!doctype html")
    if i < 0:
        i = low.find("<html")
    tail = reply[i:]
    j = tail.lower().rfind("</html>")
    html = tail[: j + len("</html>")] if j >= 0 else tail
    note = (tail[j + len("</html>"):] if j >= 0 else "").strip()[:2000]
    return html, note


async def _kill_and_reap(proc) -> None:
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    await proc.wait()


async def call_board_model(system: str, user_message: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "pi", "-p", "--model", BOARD_MODEL, "--thinking", BOARD_THINKING,
        "--no-tools", "--no-session", "--no-context-files",
        "--no-skills", "--no-extensions",
        "--extension", str(BOARD_BUDGET_EXTENSION),
        "--mode", "json",
        "--system-prompt", system, user_message,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "BOARD_MAX_TOKENS": str(BOARD_MAX_TOKENS)})
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=BOARD_TIMEOUT_S)
    except asyncio.TimeoutError:
        await _kill_and_reap(proc)
        raise TimeoutError(f"board model timed out after {BOARD_TIMEOUT_S}s")
    except asyncio.CancelledError:
        await _kill_and_reap(proc)
        raise
    reply = ""
    failure: str | None = None
    truncated = False
    for line in out.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") == "message_end":
            msg = d.get("message", {}) or {}
            if msg.get("role") == "assistant":
                for c in msg.get("content", []) or []:
                    if isinstance(c, dict) and c.get("type") == "text":
                        reply += c.get("text", "")
            error_message = msg.get("errorMessage")
            if error_message or msg.get("stopReason") in ("error", "aborted"):
                failure = str(error_message or msg.get("stopReason"))
            elif msg.get("stopReason") == "length":
                truncated = True
    if failure:
        raise RuntimeError(f"board model error: {failure[:500]}")
    if truncated:
        raise ValueError("board model reply truncated (length stop reason)")
    if not reply and proc.returncode:
        tail = out.decode("utf-8", errors="replace").strip()[-500:]
        raise RuntimeError(f"board model failed (exit {proc.returncode}): {tail}")
    return reply


def apply_csp(html: str) -> str:
    """Wrap board html with the served-board CSP meta tag.

    The tutor's screenshot then shares the child's effective policy instead of
    rendering with no policy (where blocked assets would misleadingly load).
    """
    meta = f'<meta http-equiv="Content-Security-Policy" content="{HTML_CSP}">'
    low = html.lower()
    for tag in ("<head", "<html"):
        i = low.find(tag)
        if i >= 0:
            j = html.find(">", i)
            if j >= 0:
                return html[: j + 1] + meta + html[j + 1 :]
    return meta + html


async def screenshot_board(html: str, width: int, height: int) -> bytes | None:
    """Render the settled board to PNG. None when Chromium is unavailable."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("playwright missing: tutor gets no board screenshot")
        return None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.set_content(apply_csp(html), wait_until="load", timeout=30000)
            await page.wait_for_timeout(500)
            try:
                await page.evaluate("() => { for (const a of document.getAnimations()) { try { a.finish(); } catch {} } }")
            except Exception:
                pass
            png = await page.screenshot()
            await browser.close()
            return png
    except Exception as error:
        log.warning("board screenshot failed: %s", error)
        return None


async def render_board(need: str, background: str, learner_name: str = "",
                       board_w: int = BOARD_W, board_h: int = BOARD_H,
                       device: str = "desktop", lang: str = "Swedish",
                       previous_html: str | None = None) -> dict:
    """Commission a board. Returns {html, note, png} (png may be None).

    When previous_html is given, revise that exact source: change only what
    `need` requests, preserving unrelated content, layout and controls, and
    return the complete revised document.
    """
    system = fill_system(board_w, board_h, device, lang)
    if previous_html is None:
        user_message = (
            f"## The child\n{learner_name}\n\n"
            f"## What is needed\n{background}\n\n"
            f"## The tutor's handover\n{need}\n\nMake the board now.")
    else:
        user_message = (
            f"## The child\n{learner_name}\n\n"
            f"## Current board (complete HTML source, {board_w}x{board_h})\n"
            f"{previous_html}\n\n"
            f"## Requested change\n{need}\n\n"
            f"## Context\n{background}\n\n"
            "Revise the current board: change only what was requested, preserving "
            "unrelated content, layout, text and controls. Return the complete "
            "revised HTML document starting with <!doctype html>, then after "
            "</html> explain in 2-3 sentences what changed and what the tutor "
            "should start from.")
    reply = await call_board_model(system, user_message)
    low_reply = reply.lower()
    if ("<!doctype html" in low_reply or "<html" in low_reply) and "</html>" not in low_reply:
        raise ValueError("board model returned truncated HTML (missing </html>)")
    html, note = extract_board(reply)
    if not html:
        raise ValueError("board model returned no HTML document")
    png = await screenshot_board(html, board_w, board_h)
    return {"html": html, "note": note, "png": png}
