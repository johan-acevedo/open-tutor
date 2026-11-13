"""Check the map key layout and region interaction, without provider calls.

The pages are unedited DeepSeek V4.1 Flash output for "Visa Sveriges 21 län …"
(see screen/review/2026-11-13-map-key/). What is checked:

- a wide pane puts the key beside the map, so the map can use the full height;
- a phone keeps the key under the map, and the key never covers the country;
- the 21 letter codes are all on the map when the map has room, at a readable size,
  and a code that does not fit is hidden with its key row dimmed;
- `ot.point('lan-M')` still outlines Skåne, and a patch still marks and names regions.

Run from the repo root:
  uv run --project server python screen/tools/check_map_key.py
"""

from __future__ import annotations

import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import screenkit  # noqa: E402

REVIEW = pathlib.Path(__file__).resolve().parents[1] / "review" / "2026-11-13-map-key"
# page.html and page-ref.html are the fresh pages, page-early.html is the same ask on the old shell.
# page-ref.html has a bigger answer block, so its map box is shorter: its code count is reported,
# not asserted.
BODIES = (("page.html", True), ("page-ref.html", False), ("page-early.html", True))
WIDE = (1000, 700)
PHONE = (370, 610)
MEDIUM = (760, 900)

GEOMETRY = """() => {
  const map = document.querySelector('ot-map');
  const lay = map.querySelector('.ot-vis');
  const box = lay.getBoundingClientRect();
  const key = lay.querySelector('.ot-map-legend');
  // The country as CSS pixels: a path's own box is in svg user units, which only match the
  // layer's pixels when the map was drawn at its final size.
  const rects = [...lay.querySelectorAll('.ot-region-shape')].map(s => s.getBoundingClientRect());
  const bb = rects.length ? {
    x0: Math.min(...rects.map(r => r.left)) - box.left,
    x1: Math.max(...rects.map(r => r.right)) - box.left,
    y0: Math.min(...rects.map(r => r.top)) - box.top,
    y1: Math.max(...rects.map(r => r.bottom)) - box.top
  } : null;
  const codes = [...lay.querySelectorAll('.ot-region-code')];
  const rows = [...lay.querySelectorAll('.ot-region-key')];
  const rel = r => ({left: r.left - box.left, top: r.top - box.top, right: r.right - box.left,
                     bottom: r.bottom - box.top, width: r.width, height: r.height});
  return {
    box: {w: box.width, h: box.height},
    side: key ? key.classList.contains('ot-map-legend-side') : false,
    key: key ? rel(key.getBoundingClientRect()) : null,
    rows: rows.length,
    codesTotal: codes.length,
    shown: codes.filter(c => !c.hidden).length,
    codeBoxes: codes.filter(c => !c.hidden).map(c => rel(c.getBoundingClientRect())),
    codePx: codes.length ? parseFloat(getComputedStyle(codes[0]).fontSize) : 0,
    country: bb ? {w: bb.x1 - bb.x0, h: bb.y1 - bb.y0, right: bb.x1, bottom: bb.y1} : null,
    dimRows: rows.filter(r => r.classList.contains('ot-region-key-off')).length,
    fontPx: ot.fontPx,
    issues: ot.issues
  };
}"""


def open_page(browser, body: str, size: tuple[int, int]):
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    page.set_content(screenkit.host_page(screenkit.compose(body)))
    frame = screenkit._frame(page)
    frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
    return page, frame


def geometry(browser, body: str, size: tuple[int, int]) -> dict:
    page, frame = open_page(browser, body, size)
    try:
        return frame.evaluate(GEOMETRY)
    finally:
        page.close()


def check_wide(g: dict, where: str, strict: bool) -> None:
    assert g["side"], f"{where}: the key should sit beside the map, got {g['key']}"
    assert g["rows"] == 21, f"{where}: the key has {g['rows']} rows"
    if strict:
        assert g["shown"] == 21, f"{where}: only {g['shown']} of 21 codes are on the map"
    assert g["codePx"] >= 11, f"{where}: codes at {g['codePx']} px are unreadable"
    assert g["country"]["h"] >= 0.7 * g["box"]["h"], \
        f"{where}: the map only uses {g['country']['h']:.0f} of {g['box']['h']:.0f} px"
    assert g["key"]["left"] >= g["country"]["right"], f"{where}: the key covers the map"
    assert g["key"]["height"] <= g["box"]["h"] + 1, f"{where}: the key is taller than the map box"
    if strict:
        assert not [i for i in g["issues"] if i["kind"] == "crowded"], f"{where}: {g['issues']}"
    assert not [c for c in g["codeBoxes"] if c["right"] > g["key"]["left"] + 1], \
        f"{where}: letter codes run into the key"


def check_phone(g: dict, where: str) -> None:
    assert not g["side"], f"{where}: the key must stay under the map on a phone"
    assert g["rows"] == 21, f"{where}: the key has {g['rows']} rows"
    assert g["key"]["top"] >= g["country"]["bottom"] - 1, \
        f"{where}: the key starts at {g['key']['top']:.0f} but the country ends at {g['country']['bottom']:.0f}"
    assert g["key"]["bottom"] <= g["box"]["h"] + 1, f"{where}: the key runs out of the map box"
    assert g["shown"] + g["dimRows"] == 21, \
        f"{where}: {g['shown']} codes shown and {g['dimRows']} dimmed key rows"


def check_pointing(browser, body: str, name: str) -> None:
    page, frame = open_page(browser, body, WIDE)
    try:
        assert frame.evaluate("() => ot.point('lan-M')"), f"{name}: point lan-M was refused"
        pointed = frame.evaluate(
            "() => [...document.querySelectorAll('.ot-region-shape.ot-pointed')].map(s => s.dataset.code)")
        assert pointed == ["M"], f"{name}: pointing lan-M outlined {pointed}"
        frame.evaluate("() => ot.point(null)")
        assert not frame.evaluate("() => document.querySelectorAll('.ot-region-shape.ot-pointed').length"), \
            f"{name}: pointing was not cleared"
    finally:
        page.close()


def check_patching(browser, body: str, name: str) -> None:
    patch = (REVIEW / "mark.patch.html").read_text()
    for size in (WIDE, PHONE):
        page, frame = open_page(browser, body, size)
        try:
            issues = frame.evaluate("(p) => ot.patch(p)", patch)
            where = f"{name} {size[0]}x{size[1]} patch"
            bad = [i for i in issues if i["kind"] != "crowded"]
            assert not bad, f"{where}: {bad}"
            named = frame.evaluate("() => [...document.querySelectorAll('.ot-map-label')].map(l => l.textContent)")
            for region in ("Skåne", "Stockholm", "Norrbotten"):
                assert region in named, f"{where}: {region} is not named on the map: {named}"
            g = frame.evaluate(GEOMETRY)
            assert g["rows"] == 21, f"{where}: the key has {g['rows']} rows"
            assert g["side"] == (size == WIDE), f"{where}: the key moved to the wrong side"
        finally:
            page.close()


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            print("| page | pane | text | key | codes | code size | country | map box | crowded |")
            print("|---|---|---|---|---|---|---|---|---|")
            for name, strict in BODIES:
                body = (REVIEW / name).read_text()
                for size, check in ((PHONE, check_phone), (MEDIUM, None), (WIDE, check_wide)):
                    g = geometry(browser, body, size)
                    if check is check_phone:
                        check(g, f"{name} {size[0]}x{size[1]}")
                    elif check:
                        check(g, f"{name} {size[0]}x{size[1]}", strict)
                    crowded = [i for i in g["issues"] if i["kind"] == "crowded"]
                    print(f"| {name} | {size[0]}x{size[1]} | {g['fontPx']} px | "
                          f"{'beside' if g['side'] else 'under'} | {g['shown']}/{g['codesTotal']} | "
                          f"{g['codePx']} px | {round(g['country']['w'])}x{round(g['country']['h'])} | "
                          f"{round(g['box']['w'])}x{round(g['box']['h'])} | "
                          f"{'yes' if crowded else 'no'} |")
                check_pointing(browser, body, name)
                check_patching(browser, body, name)
        finally:
            browser.close()
    print("Map key checks passed: layout, codes, pointing and patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
