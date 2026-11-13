"""Check the län map: its own drawing box, tight bounds, the key in flow, region interaction.

The pages are unedited DeepSeek V4.1 Flash output for "Visa Sveriges 21 län …"
(see screen/review/2026-11-13-map-key/, the parent folder of this change's evidence).
What is checked, without provider calls:

- the map is drawn into its own box (`.ot-map-canvas`) with the key in normal flow beside it
  (wide pane) or under it (phone), never as an overlay over sea or country;
- Sweden is fitted tightly to its 21 region polygons, so the country fills the drawing box
  instead of sitting small inside the broad `sverige` view (Norway, Finland, the Baltic);
- the 21 letter codes are on the map where the map has room, at a readable size on a wide
  pane, and a code that does not fit is hidden with its key row dimmed;
- `ot.point('lan-M')` still outlines Skåne, and a patch still marks and names regions.

Run from the repo root:
  uv run --project server python screen/tools/check_map_key.py
  uv run --project server python screen/tools/check_map_key.py --shots   # also write the PNGs

`--shell DIR` composes with another shell directory (frame.html, shell.css, shell.js), which is
how the same checks are run against the shell from before this change:
  screen/tools/check_prior_shell.sh
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import screenkit  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
REVIEW = ROOT / "review" / "2026-11-13-map-key"
OUT = ROOT / "review" / "2026-11-13-map-phone"
# page.html and page-early.html have short enough answer blocks to fit all 21 letters on a wide
# map; page-ref.html has the biggest answer block, so one letter stays in the key there.
BODIES = (("page.html", True), ("page-ref.html", False), ("page-early.html", True))
WIDE = (1000, 700)
MEDIUM = (760, 900)
PHONE = (370, 610)
PHONE_SHORT = (370, 558)

GEOMETRY = """() => {
  const lay = document.querySelector('ot-map .ot-vis');
  const canvas = lay.querySelector('.ot-map-canvas');
  const box = (canvas || lay).getBoundingClientRect();
  const key = lay.querySelector('.ot-map-legend');
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
    separate: !!canvas,
    layout: lay.classList.contains('ot-map-key-side') ? 'beside' : 'under',
    box: {w: box.width, h: box.height},
    key: key ? rel(key.getBoundingClientRect()) : null,
    keyScrollW: key ? key.scrollWidth : 0,
    rows: rows.length,
    codesTotal: codes.length,
    shown: codes.filter(c => !c.hidden).length,
    codeBoxes: codes.filter(c => !c.hidden).map(c => rel(c.getBoundingClientRect())),
    codePx: codes.length ? parseFloat(getComputedStyle(codes[0]).fontSize) : 0,
    country: bb ? {w: bb.x1 - bb.x0, h: bb.y1 - bb.y0, left: bb.x0, top: bb.y0,
                   right: bb.x1, bottom: bb.y1} : null,
    dimRows: rows.filter(r => r.classList.contains('ot-region-key-off')).length,
    fontPx: ot.fontPx,
    issues: ot.issues
  };
}"""


def open_page(browser, body: str, size: tuple[int, int], shell: pathlib.Path, shot=None):
    page = browser.new_page(viewport={"width": size[0], "height": size[1]})
    page.set_content(screenkit.host_page(screenkit.compose(body, shell)))
    frame = screenkit._frame(page)
    frame.wait_for_function("() => document.documentElement.dataset.otReady === '1'", timeout=30000)
    if shot:
        page.screenshot(path=str(shot))
    return page, frame


def geometry(browser, body: str, size: tuple[int, int], shell: pathlib.Path, shot=None) -> dict:
    page, frame = open_page(browser, body, size, shell, shot)
    try:
        return frame.evaluate(GEOMETRY)
    finally:
        page.close()


def fill(g: dict) -> tuple[float, float]:
    """How much of the drawing box the country covers, as fractions of its height and width."""
    return g["country"]["h"] / g["box"]["h"], g["country"]["w"] / g["box"]["w"]


def check_box(g: dict, where: str, layout: str) -> None:
    """The key has its own space, and Sweden fills the box the map is drawn into."""
    assert g["separate"], f"{where}: the key has no box of its own (.ot-map-canvas missing); it overlays the map"
    assert g["rows"] == 21, f"{where}: the key has {g['rows']} rows"
    assert g["layout"] == layout, f"{where}: the key is {g['layout']} the map, expected {layout}"
    if layout == "beside":
        assert g["key"]["left"] >= g["box"]["w"] - 1, f"{where}: the key starts inside the drawing box"
        assert g["keyScrollW"] <= g["key"]["width"] + 1, \
            f"{where}: the key column clips its names ({g['keyScrollW']:.0f} in {g['key']['width']:.0f} px)"
        assert g["key"]["top"] >= -1 and g["key"]["bottom"] <= g["box"]["h"] + 1, \
            f"{where}: the key does not fit the drawing box height"
        assert not [c for c in g["codeBoxes"] if c["right"] > g["key"]["left"] + 1], \
            f"{where}: letter codes run into the key"
    else:
        assert g["key"]["top"] >= g["box"]["h"] - 1, \
            f"{where}: the key starts at {g['key']['top']:.0f} inside a {g['box']['h']:.0f} px drawing box"
        assert g["key"]["right"] <= g["box"]["w"] + 1, f"{where}: the key runs out of the map"
    c = g["country"]
    assert c["left"] >= -1 and c["top"] >= -1 and c["right"] <= g["box"]["w"] + 1 and c["bottom"] <= g["box"]["h"] + 1, \
        f"{where}: the country is not inside its drawing box: {c} vs {g['box']}"
    fh, _ = fill(g)
    assert fh >= 0.85, \
        f"{where}: the country only fills {fh * 100:.0f}% of the drawing box height " \
        f"({c['h']:.0f} of {g['box']['h']:.0f} px); the fit is not tight"


def check_wide(g: dict, where: str, strict: bool) -> None:
    check_box(g, where, "beside")
    if strict:
        assert g["shown"] == 21, f"{where}: only {g['shown']} of 21 codes are on the map"
        assert not [i for i in g["issues"] if i["kind"] == "crowded"], f"{where}: {g['issues']}"
    assert g["codePx"] >= 11, f"{where}: codes at {g['codePx']} px are unreadable"


def check_phone(g: dict, where: str) -> None:
    check_box(g, where, "under")
    assert g["shown"] + g["dimRows"] == 21, \
        f"{where}: {g['shown']} codes shown and {g['dimRows']} dimmed key rows"


def check_pointing(browser, name: str, shell: pathlib.Path) -> None:
    page, frame = open_page(browser, (REVIEW / name).read_text(), WIDE, shell)
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


def check_patching(browser, name: str, shell: pathlib.Path, shots: bool) -> None:
    patch = (REVIEW / "mark.patch.html").read_text()
    for size in (WIDE, PHONE):
        shot = OUT / f"{name.removesuffix('.html')}-{size[0]}x{size[1]}-patched.png" if shots else None
        page, frame = open_page(browser, (REVIEW / name).read_text(), size, shell)
        try:
            issues = frame.evaluate("(p) => ot.patch(p)", patch)
            where = f"{name} {size[0]}x{size[1]} patch"
            bad = [i for i in issues if i["kind"] != "crowded"]
            assert not bad, f"{where}: {bad}"
            named = frame.evaluate("() => [...document.querySelectorAll('.ot-map-label')].map(l => l.textContent)")
            for region in ("Skåne", "Stockholm", "Norrbotten"):
                assert region in named, f"{where}: {region} is not named on the map: {named}"
            g = frame.evaluate(GEOMETRY)
            if shot:
                # let the redraw and its fade-in finish before the screenshot
                page.wait_for_timeout(2500)
                page.screenshot(path=str(shot))
            check_box(g, where, "beside" if size == WIDE else "under")
        finally:
            page.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shell", default=str(ROOT / "shell"), help="shell directory to compose with")
    ap.add_argument("--shots", action="store_true", help="write screenshots to the review folder")
    ap.add_argument("--table-only", action="store_true",
                    help="print the measured table and skip the assertions (used on an older shell)")
    a = ap.parse_args(argv)
    shell = pathlib.Path(a.shell).resolve()
    if a.shots:
        OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            print("| page | pane | key | codes | code size | country | drawing box | filled | crowded | text |")
            print("|---|---|---|---|---|---|---|---|---|---|")
            for name, strict in BODIES:
                body = (REVIEW / name).read_text()
                for size in (PHONE_SHORT, PHONE, MEDIUM, WIDE):
                    shot = OUT / f"{name.removesuffix('.html')}-{size[0]}x{size[1]}.png" if a.shots else None
                    g = geometry(browser, body, size, shell, shot)
                    where = f"{name} {size[0]}x{size[1]}"
                    if not a.table_only:
                        if size == WIDE:
                            check_wide(g, where, strict)
                        elif size[0] <= 600:
                            check_phone(g, where)
                        else:
                            check_box(g, where, "beside")
                    fh, fw = fill(g)
                    crowded = [i for i in g["issues"] if i["kind"] == "crowded"]
                    dense = [i for i in g["issues"] if i["kind"] == "dense"]
                    box = f"{round(g['box']['w'])}x{round(g['box']['h'])}"
                    print(f"| {name} | {size[0]}x{size[1]} | {g['layout']}{'' if g['separate'] else ' (overlay)'} | "
                          f"{g['shown']}/{g['codesTotal']} | "
                          f"{g['codePx']} px | {round(g['country']['w'])}x{round(g['country']['h'])} | "
                          f"{box} | "
                          f"{fh * 100:.0f}% h / {fw * 100:.0f}% w | {'yes' if crowded else 'no'} | "
                          f"{g['fontPx']} px{' (dense)' if dense else ''} |")
                if a.table_only:
                    continue
                check_pointing(browser, name, shell)
                check_patching(browser, name, shell, a.shots)
        finally:
            browser.close()
    if a.table_only:
        return 0
    print("Map checks passed: separate key box, tight country bounds, codes, pointing and patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
