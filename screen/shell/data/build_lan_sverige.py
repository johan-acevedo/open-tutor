"""Build lan-sverige.json: Sweden's 21 län, for ot-map.

Source: Natural Earth 10m admin-1 states/provinces, public domain, pinned commit
ca96624a56bd078437bca8184e78163e5039ad19 of github.com/nvkelso/natural-earth-vector
(the same source and commit as the countries file the shell loads from jsDelivr).
The 10m world file is 40 MB and over jsDelivr's file limit, so it can never be fetched
by a page. This script keeps the 21 Swedish features, simplifies them with mapshaper
(topology preserving: neighbours keep identical lines, so shared borders stay clean)
and quantises the coordinates to 1/1000 degree, about 110 m.

  python3 screen/shell/data/build_lan_sverige.py [--ne path/to/ne_10m_admin_1.geojson]
                                                 [--simplify 25]

Needs `npx mapshaper` (downloads once) and, for the first run, network access.
Writes lan-sverige.json next to this file. Re-run it after changing --simplify.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "lan-sverige.json"
COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/" + COMMIT +
       "/geojson/ne_10m_admin_1_states_provinces.geojson")
MAPSHAPER = "mapshaper@0.6.109"
SCALE = 1000  # 1/1000 degree ≈ 110 m

# Natural Earth spells them without å ä ö; the map shows what Swedish children read.
NAMES = {
    "SE-AB": "Stockholm", "SE-AC": "Västerbotten", "SE-BD": "Norrbotten", "SE-C": "Uppsala",
    "SE-D": "Södermanland", "SE-E": "Östergötland", "SE-F": "Jönköping", "SE-G": "Kronoberg",
    "SE-H": "Kalmar", "SE-I": "Gotland", "SE-K": "Blekinge", "SE-M": "Skåne", "SE-N": "Halland",
    "SE-O": "Västra Götaland", "SE-S": "Värmland", "SE-T": "Örebro", "SE-U": "Västmanland",
    "SE-W": "Dalarna", "SE-X": "Gävleborg", "SE-Y": "Västernorrland", "SE-Z": "Jämtland",
}


def download() -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp()) / "ne_10m_admin_1.geojson"
    print("downloading natural earth admin-1 (40 MB) …", file=sys.stderr)
    urllib.request.urlretrieve(URL, tmp)
    return tmp


def simplify(src: pathlib.Path, pct: int) -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp())
    sweden = tmp / "sweden.geojson"
    data = json.loads(src.read_text())
    features = [f for f in data["features"] if (f["properties"] or {}).get("adm0_a3") == "SWE"]
    if len(features) != 21:
        raise SystemExit(f"expected 21 Swedish features, got {len(features)}")
    sweden.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    out = tmp / "lan.geojson"
    cmd = ["npx", "--yes", MAPSHAPER, str(sweden), "-simplify", f"{pct}%", "keep-shapes",
           "-o", str(out), "format=geojson", "precision=0.001"]
    print("running", " ".join(cmd), file=sys.stderr)
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
    return out


def quantise(v: float) -> int:
    return int(round(v * SCALE))


def build(simplified: pathlib.Path) -> dict:
    data = json.loads(simplified.read_text())
    regions = []
    for f in sorted(data["features"], key=lambda f: f["properties"]["iso_3166_2"]):
        p = f["properties"]
        code = p["iso_3166_2"].removeprefix("SE-")
        g = f["geometry"] or {}
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        parts = []
        for poly in polys:  # no holes in these 21; the outer ring is the part
            ring = poly[0]
            flat = []
            for lon, lat in ring:
                flat += [quantise(lon), quantise(lat)]
            if len(flat) >= 8:  # a triangle or better on the 1/1000 grid
                parts.append(flat)
        regions.append({
            "code": code,
            "name": NAMES[f"SE-{code}"],
            "label": [quantise(p["longitude"]), quantise(p["latitude"])],
            "parts": parts,
        })
    obj = {
        "note": ("Sveriges 21 län. Natural Earth 10m admin-1 states/provinces, public domain, "
                 "nvkelso/natural-earth-vector@" + COMMIT[:8] + ", simplified with mapshaper, "
                 "coordinates as whole 1/1000 degrees (about 110 m). Made by build_lan_sverige.py."),
        "scale": SCALE,
        "regions": regions,
    }
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if "<" in text:
        raise SystemExit("data must not contain '<': it is inlined in a <script> tag")
    return obj


def main() -> int:
    args = sys.argv[1:]
    src = pathlib.Path(args[args.index("--ne") + 1]) if "--ne" in args else download()
    pct = int(args[args.index("--simplify") + 1]) if "--simplify" in args else 25
    obj = build(simplify(src, pct))
    OUT.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
    points = sum(len(part) for r in obj["regions"] for part in r["parts"]) // 2
    print(f"{OUT.name}: {len(obj['regions'])} län, {points} points, {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
