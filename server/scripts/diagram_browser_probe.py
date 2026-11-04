"""The diagram card in a real browser, driven by the real tutor tools over real LiveKit RPC.

A local LiveKit server (no cloud, no providers, no quota) carries the session. This script plays
the tutor worker: it joins the room with the real `Tutor` class and calls the same tools the model
calls (`show_diagram`, `add_to_diagram`, `edit_diagram`, `remove_from_diagram`, `focus_diagram`,
`show_steps`, `focus_step`). Chromium (Playwright) is the child's browser. Nothing is spoken:
there is no model, speech recognition or voice. It checks what the browser really drew, not what
the tools reported.

    docker run --rm -d --name ot-livekit --network host livekit/livekit-server --dev \
        --bind 127.0.0.1 --node-ip 127.0.0.1
    (cd ../web && npm ci && npm run build)
    uv run --with playwright python scripts/diagram_browser_probe.py --out /tmp/diagram-probe

Needs Playwright with a Chromium it can start (PLAYWRIGHT_CHROMIUM overrides the executable).
Fictional material only. Not part of CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from livekit import api, rtc
from playwright.async_api import async_playwright

from open_tutor.agent import Tutor
from open_tutor.board import Step
from open_tutor.diagram import LinkSpec, NodeSpec

SERVER = Path(__file__).resolve().parents[1]
LIVEKIT_URL = "ws://127.0.0.1:7880"
RESULTS: list[dict] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    RESULTS.append({"check": name, "ok": bool(ok), "detail": detail if isinstance(detail, (str, int, float, list, dict)) else str(detail)})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail != "" else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def chromium_path() -> str | None:
    if os.environ.get("PLAYWRIGHT_CHROMIUM"):
        return os.environ["PLAYWRIGHT_CHROMIUM"]
    found = sorted((Path.home() / ".cache/ms-playwright").glob("chromium-*/chrome-linux64/chrome"))
    return str(found[-1]) if found else None


SCENE_JS = """
(id) => {
  const el = document.querySelector(`[data-board-id="${id}"] .ot-diagram-canvas`);
  const api = el && el.excalidrawApi;
  if (!api) return null;
  const s = api.getAppState();
  return {
    rev: el.getAttribute('data-scene-rev'),
    zoom: s.zoom.value, scrollX: s.scrollX, scrollY: s.scrollY, width: s.width, height: s.height,
    elements: api.getSceneElements().map(e => ({
      id: e.id, type: e.type, x: e.x, y: e.y, w: e.width, h: e.height, text: e.text,
      containerId: e.containerId, stroke: e.strokeColor, opacity: e.opacity, points: e.points,
      font: e.fontFamily, lines: e.text ? e.text.split('\\n').length : 0,
    })),
  };
}
"""


class Probe:
    def __init__(self, browser, base: str, out: Path, livekit_container: str = "ot-livekit") -> None:
        self.browser, self.base, self.out = browser, base, out
        self.livekit_container = livekit_container

    @asynccontextmanager
    async def session(self, name: str, viewport=(1366, 768), mobile=False, learner="Leo"):
        context = await self.browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            is_mobile=mobile, has_touch=mobile, device_scale_factor=2 if mobile else 1,
            permissions=["microphone"],
        )
        page = await context.new_page()
        s = Session(self, name, context, page)
        page.on("request", lambda r: s.requests.append(r.url))
        page.on("requestfailed", lambda r: s.failed.append((r.url, r.failure)))
        page.on("pageerror", lambda e: s.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and s.console.append(m.text))
        try:
            await s.start(learner)
            yield s
        finally:
            await s.close()
            await context.close()


class Session:
    def __init__(self, probe: Probe, name: str, context, page) -> None:
        self.probe, self.name, self.context, self.page = probe, name, context, page
        self.requests: list[str] = []
        self.failed: list[tuple] = []
        self.errors: list[str] = []
        self.console: list[str] = []
        self.room: rtc.Room | None = None
        self.tutor: Tutor | None = None
        self.rpc_log: list[tuple] = []

    async def start(self, learner: str) -> None:
        page = self.page
        await page.goto(self.probe.base)
        await page.fill("input[aria-label='Förnamn']", learner)
        await page.select_option("select[aria-label='Årskurs']", "7")
        async with page.expect_response("**/api/session") as waiting:
            await page.click(".ot-start-btn")
        room_name = (await (await waiting.value).json())["room"]
        token = (
            api.AccessToken("devkey", "secret").with_identity("probe-tutor")
            .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish_data=True)).to_jwt()
        )
        self.room = rtc.Room()
        await self.room.connect(LIVEKIT_URL, token)
        child = None
        for _ in range(100):
            child = next((p for p in self.room.remote_participants.values() if p.identity.startswith("learner-")), None)
            if child:
                break
            await asyncio.sleep(0.1)
        assert child, "the browser never joined the room"
        self.tutor = Tutor({"name": learner, "grade": 7}, self.room)
        self.tutor.child_identity = child.identity
        real_rpc = self.tutor._rpc

        async def logged(method, payload, timeout=6.0):
            started = time.monotonic()
            ok = await real_rpc(method, payload, timeout)
            self.rpc_log.append((method, payload.get("id"), payload.get("rev"), ok, round(time.monotonic() - started, 2)))
            return ok

        self.tutor._rpc = logged
        await page.wait_for_selector(".ot-bottombar")

    async def close(self) -> None:
        if self.room:
            await self.room.disconnect()

    async def scene(self, board_id: str):
        return await self.page.evaluate(SCENE_JS, board_id)

    async def shot(self, name: str, selector: str | None = None) -> str:
        path = self.probe.out / f"{name}.png"
        if selector:
            await self.page.locator(selector).first.screenshot(path=str(path))
        else:
            await self.page.screenshot(path=str(path))
        return str(path)

    def hosts(self) -> set[str]:
        return {urlparse(u).netloc for u in self.requests if u.startswith(("http", "ws"))}


# ---- scene consistency ------------------------------------------------------------------------


def rect_edge_distance(px, py, r):
    """Distance from a point to the outline of rectangle r (0 on the edge, positive outside)."""
    dx = max(r["x"] - px, 0, px - (r["x"] + r["w"]))
    dy = max(r["y"] - py, 0, py - (r["y"] + r["h"]))
    return math.hypot(dx, dy)


def scene_consistent(scene, diagram) -> list[str]:
    """Every node has its label centred in its box, every arrow runs edge to edge, nothing is stale."""
    problems = []
    els = {e["id"]: e for e in scene["elements"]}
    rects = {e["id"]: e for e in scene["elements"] if e["type"] == "rectangle"}
    arrows = {e["id"]: e for e in scene["elements"] if e["type"] == "arrow"}
    texts = [e for e in scene["elements"] if e["type"] == "text"]
    if set(rects) != {f"n-{n}" for n in diagram.nodes}:
        problems.append(f"nodes drawn {sorted(rects)} != model {sorted(diagram.nodes)}")
    if set(arrows) != {f"l-{k}" for k in diagram.links}:
        problems.append(f"arrows drawn {sorted(arrows)} != model {sorted(diagram.links)}")
    for t in texts:
        owner = els.get(t["containerId"])
        if not owner:
            problems.append(f"orphan text {t['text']!r}")
    for node in diagram.nodes.values():
        rect = rects.get(f"n-{node.id}")
        label = next((t for t in texts if t["containerId"] == f"n-{node.id}"), None)
        if not rect or not label:
            problems.append(f"node {node.id} lacks a box or a label")
            continue
        if label["text"].replace("\n", " ") != node.text:
            problems.append(f"label {label['text']!r} != {node.text!r}")
        cx, cy = label["x"] + label["w"] / 2, label["y"] + label["h"] / 2
        if abs(cx - (rect["x"] + rect["w"] / 2)) > 2 or abs(cy - (rect["y"] + rect["h"] / 2)) > 2:
            problems.append(f"label of {node.id} is off centre")
        if label["w"] > rect["w"] + 1 or label["h"] > rect["h"] + 1:
            problems.append(f"label of {node.id} is bigger than its box")
        if abs((rect["x"] + rect["w"] / 2) - node.x) > 1 or abs((rect["y"] + rect["h"] / 2) - node.y) > 1:
            problems.append(f"box of {node.id} is not at the model position")
    for link in diagram.links.values():
        arrow = arrows.get(f"l-{link.id}")
        if not arrow:
            continue
        a, b = rects[f"n-{link.source}"], rects[f"n-{link.target}"]
        (x0, y0), (x1, y1) = arrow["points"][0], arrow["points"][-1]
        start, end = (arrow["x"] + x0, arrow["y"] + y0), (arrow["x"] + x1, arrow["y"] + y1)
        for point, rect, which in ((start, a, "start"), (end, b, "end")):
            gap = rect_edge_distance(*point, rect)
            if not (3 <= gap <= 9):
                problems.append(f"arrow {link.id} {which} is {gap:.1f}px from its box (want about 6)")
        label = next((t for t in texts if t["containerId"] == f"l-{link.id}"), None)
        if bool(link.label) != bool(label):
            problems.append(f"arrow {link.id} label mismatch")
        if label:
            mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
            if math.hypot(label["x"] + label["w"] / 2 - mx, label["y"] + label["h"] / 2 - my) > 12:
                problems.append(f"label of arrow {link.id} is away from its midpoint")
    return problems


def lazy_download(requests: list[str], base: str) -> dict:
    """Bytes of the built files this session fetched after the page itself (raw and gzipped)."""
    import gzip

    dist = SERVER.parent / "web" / "dist"
    raw = packed = count = 0
    for url in dict.fromkeys(requests):
        path = url.removeprefix(base).split("?")[0]
        if not (path.startswith("/assets/") or path.startswith("/excalidraw/")):
            continue
        file = dist / path.lstrip("/")
        if file.is_file() and "DiagramCanvas" not in path and "index-" in path and path.endswith(".js"):
            continue  # the entry bundle every session loads
        if file.is_file():
            data = file.read_bytes()
            raw, packed, count = raw + len(data), packed + len(gzip.compress(data)), count + 1
    return {"files": count, "kB_raw": round(raw / 1000), "kB_gzip": round(packed / 1000)}


def nodes(*pairs):
    return [NodeSpec(id=i, text=t) for i, t in pairs]


def box_of(scene, node_id):
    e = next(e for e in scene["elements"] if e["id"] == f"n-{node_id}")
    return (round(e["x"]), round(e["y"]))


# ---- scenarios --------------------------------------------------------------------------------


async def scenario_desktop(probe: Probe) -> None:
    async with probe.session("desktop") as s:
        t, page = s.tutor, s.page
        check("no drawing library is requested before the first diagram", not any("DiagramCanvas" in u for u in s.requests))

        first = await t.show_diagram(None, title="Vattnets kretslopp", nodes=nodes(("kretslopp", "Vattnets kretslopp")))
        check("show_diagram returns only after the browser drew it", "is now visible (revision 1)" in first, first)
        scene = await s.scene("b1")
        check("scene shows revision 1 right after the tool returned", scene and scene["rev"] == "1" and sum(e["type"] == "rectangle" for e in scene["elements"]) == 1)
        check("the lazy chunk was fetched on demand", any("DiagramCanvas" in u for u in s.requests))
        check("download size of the first diagram (informational, from the files served)", True, lazy_download(s.requests, probe.base))
        check("the board switched to the teaching layout", await page.locator(".ot-main-teaching").count() == 1)

        steps = [
            ("avdunstning", "Avdunstning", "värms av solen"),
            ("moln", "Moln", "vattenånga kyls"),
            ("regn", "Nederbörd", None),
            ("hav", "Hav och sjöar", "samlas i"),
        ]
        seen: dict[str, tuple] = {}
        for i, (node_id, text, label) in enumerate(steps):
            result = await t.add_to_diagram(None, "b1", nodes((node_id, text)), [LinkSpec(source="kretslopp", target=node_id, label=label)])
            scene = await s.scene("b1")
            diagram = t.diagrams["b1"]
            problems = scene_consistent(scene, diagram)
            moved = [n for n, pos in seen.items() if box_of(scene, n) != pos]
            check(f"mind map step {i + 2}: {text!r} drawn, ack after render", scene["rev"] == str(diagram.rev) and "is now visible" in result and not problems and not moved, problems or moved or "")
            seen = {n: box_of(scene, n) for n in diagram.nodes}
            if i == 1:
                await s.shot("01-mindmap-grows-3-nodes", "[data-board-id='b1']")
        await s.shot("02-mindmap-grown", "[data-board-id='b1']")

        before = (await s.scene("b1"))
        await t.edit_diagram(None, "b1", "moln", text="Moln som bildas när vattenångan kyls")
        await t.edit_diagram(None, "b1", "l1", text="värms av solen och havet")
        scene = await s.scene("b1")
        problems = scene_consistent(scene, t.diagrams["b1"])
        grown = next(e for e in scene["elements"] if e["id"] == "n-moln")["w"] >= next(e for e in before["elements"] if e["id"] == "n-moln")["w"]
        check("edit: longer label and longer arrow label keep labels centred and arrows edge to edge", not problems and grown, problems)
        await s.shot("03-after-edit", "[data-board-id='b1']")

        await t.remove_from_diagram(None, "b1", ["avdunstning"])
        scene = await s.scene("b1")
        problems = scene_consistent(scene, t.diagrams["b1"])
        gone = not any("avdunstning" in e["id"] for e in scene["elements"]) and not any(e["id"] == "l-l1" for e in scene["elements"])
        check("remove: box, label and its arrow are gone, the rest is consistent", not problems and gone, problems)

        unfocused_zoom = (await s.scene("b1"))["zoom"]
        result = await t.focus_diagram(None, "b1", ["regn"])
        scene = await s.scene("b1")
        by_id = {e["id"]: e for e in scene["elements"]}
        check("focus: the node is highlighted, the rest dimmed, and the call waited for the render",
              "is now visible" in result and scene["rev"] == str(t.diagrams["b1"].rev)
              and by_id["n-regn"]["stroke"].lower() == "#22d3ee" and by_id["n-hav"]["opacity"] == 45 and by_id["n-regn"]["opacity"] == 100)
        await page.wait_for_timeout(500)  # camera animation
        zoom_after = (await s.scene("b1"))["zoom"]
        check("focus: the camera moved in on the node", zoom_after > unfocused_zoom, f"zoom {unfocused_zoom:.2f} -> {zoom_after:.2f}")
        await s.shot("04-focus-node", "[data-board-id='b1']")
        await t.focus_diagram(None, "b1", None)
        await page.wait_for_timeout(500)
        scene = await s.scene("b1")
        check("clearing the focus restores every node", all(e["opacity"] == 100 for e in scene["elements"] if e["type"] != "text"))

        # Text alternative.
        card = page.locator("[data-board-id='b1']")
        label = await card.locator(".ot-diagram-stage").get_attribute("aria-label")
        described = await card.locator(".ot-diagram-stage").get_attribute("aria-describedby")
        text = await page.locator(f"#{described}").text_content() if described else ""
        check("a readable text alternative lists the connections", "Tankekarta" in (label or "") and "Vattnets kretslopp → Moln som bildas när vattenångan kyls" in text and "avdunstning" not in text.lower(), {"label": label, "text": text})
        await card.locator("summary").click()
        await s.shot("05-text-alternative-open", "[data-board-id='b1']")

        # KaTeX card beside the diagram, both highlighted.
        await t.show_steps(None, title="Ekvation", steps=[Step(tex="3x + 5 = 20"), Step(tex="3x = 15", op="-5"), Step(tex="x = 5", op="\\div 3")])
        await t.focus_step(None, "b2", 1)
        await t.focus_diagram(None, "b1", ["kretslopp", "moln"])
        await page.wait_for_timeout(500)
        focused_row = await page.locator("[data-board-id='b2'] .ot-step-eq.focused").count()
        scene = await s.scene("b1")
        check("KaTeX steps card and the diagram coexist, both highlighted", focused_row == 1 and (await page.locator("[data-board-id='b2'] .katex").count()) >= 3 and {e["id"] for e in scene["elements"] if e["stroke"].lower() == "#22d3ee" and e["type"] == "rectangle"} == {"n-kretslopp", "n-moln"})
        await s.shot("06-katex-and-diagram", ".ot-board-scroll")

        # Page scroll passes through a non-interactive diagram; the toggle makes it zoomable.
        await page.evaluate("document.querySelector('.ot-board-scroll').scrollTop = 0")
        box = await page.locator("[data-board-id='b1'] .ot-diagram-stage").bounding_box()
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.mouse.wheel(0, 200)
        await page.wait_for_timeout(300)
        scrolled = await page.evaluate("document.querySelector('.ot-board-scroll').scrollTop")
        check("the page scrolls over a diagram that is not unlocked", scrolled > 0, scrolled)
        await card.get_by_role("button", name="Zooma och flytta").click()
        before_zoom = (await s.scene("b1"))["zoom"]
        box = await page.locator("[data-board-id='b1'] .ot-diagram-stage").bounding_box()
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.keyboard.down("Control")
        await page.mouse.wheel(0, -300)
        await page.keyboard.up("Control")
        await page.wait_for_timeout(400)
        after_zoom = (await s.scene("b1"))["zoom"]
        check("once unlocked the child can zoom this diagram", after_zoom != before_zoom, f"{before_zoom:.2f} -> {after_zoom:.2f}")

        # Chemistry flow with generic labels only.
        flow = await t.show_diagram(
            None, title="Förbränning av metan",
            nodes=[NodeSpec(id="m", text="Metan (CH₄)", role="step"), NodeSpec(id="o", text="Syre (O₂)", role="step"),
                   NodeSpec(id="r", text="Förbränning", role="center"), NodeSpec(id="c", text="Koldioxid (CO₂)", role="result"),
                   NodeSpec(id="w", text="Vatten (H₂O)", role="result")],
            links=[LinkSpec(source="m", target="r"), LinkSpec(source="o", target="r"),
                   LinkSpec(source="r", target="c", label="bildas"), LinkSpec(source="r", target="w", label="bildas")],
            layout="flow",
        )
        scene = await s.scene("b3")
        problems = scene_consistent(scene, t.diagrams["b3"])
        texts = {e["text"] for e in scene["elements"] if e["type"] == "text"}
        check("generic chemistry flow renders its labels with subscripts", "is now visible" in flow and not problems and {"Metan (CH₄)", "Koldioxid (CO₂)", "Vatten (H₂O)"} <= texts, problems or sorted(texts))
        await s.shot("07-chemistry-flow", "[data-board-id='b3']")

        # Updates that overlap are applied in order.
        ops = [t.add_to_diagram(None, "b1", nodes((f"x{i}", f"Idé {i}")), [LinkSpec(source="kretslopp", target=f"x{i}")]) for i in range(5)]
        results = await asyncio.gather(*ops)
        scene = await s.scene("b1")
        order = [r[2] for r in s.rpc_log if r[1] == "b1"][-5:]
        check("five overlapping tool calls are sent in revision order and all drawn", order == sorted(order) and all("is now visible" in r for r in results) and not scene_consistent(scene, t.diagrams["b1"]) and scene["rev"] == str(t.diagrams["b1"].rev), order)

        # Network: only our own origin and the local LiveKit server, fonts from our server.
        hosts = s.hosts()
        allowed = {urlparse(probe.base).netloc, urlparse(LIVEKIT_URL).netloc}
        fonts = [u for u in s.requests if "/excalidraw/fonts/" in u]
        check("no third-party network: only the app and LiveKit", hosts <= allowed, sorted(hosts))
        check("diagram fonts were loaded from our own server", any("/Nunito/" in u for u in fonts), [u.rsplit("/", 1)[-1][:30] for u in fonts])
        check("no failed requests or page errors", not s.failed and not s.errors, {"failed": s.failed[:3], "errors": s.errors[:3], "console": s.console[:3]})
        await s.shot("08-desktop-full")
        check("desktop: no horizontal overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))


async def scenario_mobile(probe: Probe) -> None:
    async with probe.session("mobile", viewport=(390, 844), mobile=True) as s:
        t, page = s.tutor, s.page
        await t.show_diagram(None, title="Vattnets kretslopp", nodes=nodes(("k", "Vattnets kretslopp"), ("a", "Avdunstning"), ("m", "Moln")),
                             links=[LinkSpec(source="k", target="a"), LinkSpec(source="a", target="m", label="blir")])
        await t.show_steps(None, title="Ekvation", steps=[Step(tex="3x + 5 = 20"), Step(tex="3x = 15", op="-5")])
        scene = await s.scene("b1")
        problems = scene_consistent(scene, t.diagrams["b1"])
        check("390px: the diagram is drawn and consistent", not problems, problems)
        box = await page.locator("[data-board-id='b1'] .ot-diagram-stage").bounding_box()
        bar = await page.locator(".ot-bottombar").bounding_box()
        check("390px: no horizontal page overflow", await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))
        check("390px: the fixed bottom bar stays inside the viewport", bar["y"] + bar["height"] <= 844 and bar["width"] <= 390, bar)
        await s.shot("09-mobile-390", None)
        await s.shot("10-mobile-390-card", "[data-board-id='b1']")
        info = {"stage_width": box["width"], "stage_height": box["height"], "zoom": scene["zoom"]}
        check("390px: measured stage size (informational)", True, info)


async def scenario_lazy_failure(probe: Probe) -> None:
    async with probe.session("lazy-failure") as s:
        t, page = s.tutor, s.page
        await page.route("**/assets/DiagramCanvas-*.js", lambda route: route.abort())
        await t.show_text(None, title="Ord", markdown="Fotosyntes: $6CO_2 + 6H_2O$")
        started = time.monotonic()
        result = await t.show_diagram(None, title="Kolets kretslopp", nodes=nodes(("a", "Atmosfär"), ("b", "Växter")), links=[LinkSpec(source="a", target="b", label="tas upp")])
        check("lazy chunk blocked: the tool says the board did not confirm", "did not confirm" in result and "is now visible" not in result, result[:90])
        check("the failure is reported at once, not after a timeout", time.monotonic() - started < 6, round(time.monotonic() - started, 1))
        err = page.locator("[data-board-id='b2'] .ot-diagram-error")
        check("the card says so visibly, offers a retry and shows the text version", await err.count() == 1 and not await page.locator("[data-board-id='b2'] .ot-diagram-stage").is_visible() and await page.locator("[data-board-id='b2'] .ot-diagram-text[open]").count() == 1 and "Atmosfär → Växter (tas upp)" in await page.locator("[data-board-id='b2'] .ot-diagram-text").inner_text())
        check("the other card and the session still work", await page.locator("[data-board-id='b1'] .katex").count() > 0 and (await page.locator(".ot-bottombar").count()) == 1)
        await s.shot("11-lazy-load-failed", "[data-board-id='b2']")
        await page.unroute("**/assets/DiagramCanvas-*.js")
        await page.get_by_role("button", name="Försök igen").click()
        healed = await t.add_to_diagram(None, "b2", nodes(("c", "Hav")), [LinkSpec(source="a", target="c")])
        scene = await s.scene("b2")
        check("after the connection returns, retry and the next call draw the whole diagram", "is now visible" in healed and scene and not scene_consistent(scene, t.diagrams["b2"]) and await page.locator("[data-board-id='b2'] .ot-diagram-error").count() == 0, scene_consistent(scene, t.diagrams["b2"]) if scene else "no scene")
        await s.shot("12-lazy-load-recovered", "[data-board-id='b2']")


async def scenario_font_failure(probe: Probe) -> None:
    async with probe.session("font-failure") as s:
        t, page = s.tutor, s.page
        await page.route("**/excalidraw/fonts/Nunito/**", lambda route: route.abort())
        result = await t.show_diagram(None, title="Test", nodes=nodes(("a", "Åäö")))
        check("font files missing: the tool says it was not confirmed (no false success)", "did not confirm" in result, result[:90])
        check("font files missing: the card shows the problem and the text version", await page.locator("[data-board-id='b1'] .ot-diagram-error").count() == 1 and await page.locator("[data-board-id='b1'] .ot-diagram-text[open]").count() == 1)
        await s.shot("13-font-failed", "[data-board-id='b1']")


async def scenario_reconnect(probe: Probe) -> None:
    """Freeze the LiveKit server for longer than the RPC timeout, then let both sides reconnect."""
    async with probe.session("reconnect") as s:
        t, page = s.tutor, s.page
        await t.show_diagram(None, title="Karta", nodes=nodes(("a", "A")))
        frozen = subprocess.run(["docker", "pause", probe.livekit_container], capture_output=True).returncode == 0
        if not frozen:
            check("reconnect scenario needs `docker pause` on the LiveKit container", False, probe.livekit_container)
            return
        try:
            during = await t.add_to_diagram(None, "b1", nodes(("b", "B")), [LinkSpec(source="a", target="b")])
        finally:
            subprocess.run(["docker", "unpause", probe.livekit_container], capture_output=True)
        check("server frozen past the RPC timeout: the tool does not claim success", "did not confirm" in during and "is now visible" not in during, during[:80])
        banner = None
        for _ in range(10):  # the browser's banner, if it noticed, then recovery
            banner = await page.locator(".ot-banner").count()
            if banner:
                break
            await asyncio.sleep(0.5)
        for _ in range(80):
            if not await page.locator(".ot-banner").count():
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.0)
        after = await t.add_to_diagram(None, "b1", nodes(("c", "C")), [LinkSpec(source="b", target="c")])
        scene = await s.scene("b1")
        problems = scene_consistent(scene, t.diagrams["b1"]) if scene else ["no scene"]
        check("after the connection is back, the next change redraws the whole diagram (A, B and C)",
              "is now visible" in after and not problems and scene["rev"] == str(t.diagrams["b1"].rev) and len(t.diagrams["b1"].nodes) == 3,
              {"after": after[:70], "problems": problems, "banner_seen": bool(banner)})
        await s.shot("14-after-reconnect", "[data-board-id='b1']")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", default="")
    parser.add_argument("--livekit-container", default="ot-livekit", help="Docker container paused in the reconnect scenario")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    port = free_port()
    env = {**os.environ, "LIVEKIT_URL": LIVEKIT_URL, "LIVEKIT_API_KEY": "devkey", "LIVEKIT_API_SECRET": "secret",
           "TUTOR_AGENT_NAME": "diagram-probe-nobody", "TUTOR_ACCESS_CODE": "", "TUTOR_MAX_SESSIONS_PER_HOUR": "100"}
    web = subprocess.Popen([sys.executable, "-m", "uvicorn", "open_tutor.web:app", "--port", str(port), "--log-level", "warning"], cwd=SERVER, env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                await asyncio.sleep(0.2)
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                executable_path=chromium_path(),
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
            )
            probe = Probe(browser, base, out, args.livekit_container)
            scenarios = [("desktop", scenario_desktop), ("mobile", scenario_mobile), ("lazy", scenario_lazy_failure),
                         ("font", scenario_font_failure), ("reconnect", scenario_reconnect)]
            for name, fn in scenarios:
                if args.only and name != args.only:
                    continue
                print(f"--- {name}", flush=True)
                try:
                    await fn(probe)
                except Exception as error:  # a crashed scenario is a failure, not a skip
                    check(f"scenario {name} ran to the end", False, repr(error))
            await browser.close()
    finally:
        web.terminate()
    (out / "results.json").write_text(json.dumps(RESULTS, indent=1, ensure_ascii=False))
    failed = [r for r in RESULTS if not r["ok"]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
