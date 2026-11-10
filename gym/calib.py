#!/usr/bin/env python3
"""Judge calibration: agreement of each judge with the Opus/Sol reference on the calibration ids.
    python3 gym/calib.py --round r0 [--show JUDGE]"""
import argparse, collections, glob, json, os
from pathlib import Path
DATA = Path(os.environ.get("GYM_DATA", Path.home() / "gym-data" / "board-gym"))
ap = argparse.ArgumentParser(); ap.add_argument("--round", default="r0"); ap.add_argument("--show")
a = ap.parse_args()
jd = DATA / "judge" / a.round
v = collections.defaultdict(dict)
for f in glob.glob(str(jd / "raw" / "*.json")):
    b, j = Path(f).stem.split("."); v[b][j] = json.load(open(f))
ids = (jd / "calib-ids.txt").read_text().strip().split(",")
key = json.load(open(jd / "key.json"))
rows = collections.defaultdict(collections.Counter)
for b in ids:
    d = v[b]; ref = all(d[o]["correct"] for o in ("opus", "sol") if o in d)
    for j in d:
        if j in ("opus", "sol"): continue
        rows[j]["agree" if d[j]["correct"] == ref else ("lenient" if d[j]["correct"] else "strict")] += 1
        if j == a.show and d[j]["correct"] != ref:
            o = [x for x in ("opus", "sol") if x in d][0]
            print(b, key[b]["member"][:10], "ref", ref, "| ref:", "; ".join(d[o]["issues"])[:120],
                  "|| judge:", "; ".join(d[j]["issues"])[:120])
for j, c in sorted(rows.items()):
    n = sum(c.values()); print(f"{j:10} n={n} agree={c['agree']} lenient={c['lenient']} strict={c['strict']}")
