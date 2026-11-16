#!/usr/bin/env python3
"""Global TTFT bake-off via Globalping HTTP measurements (ready to run after deploy).

Prereqs: worker deployed (see README below), WORKER_BASE env =
  https://open-tutor-llm-bench.<subdomain>.workers.dev/<32hex>
Usage: WORKER_BASE=... python3 run-global.py
Writes global-results.jsonl (one line per probe run). No keys leave this machine:
  probes only GET the secret path; provider keys stay inside the Worker.

Design: per city, 6 measurements x limit 5, alternating A B C A B C
  (10 runs/backend/city, interleaved against cache/time drift).
  10 cities x 30 runs = 300 probe executions; the create->poll cycle self-limits
  below the 250/hr free tier, with 429 backoff just in case.
"""
import json, os, sys, time, urllib.request

BASE = os.environ["WORKER_BASE"].rstrip("/")
CITIES = [
    ("AU", "Sydney"), ("US", "Phoenix"), ("US", "Ashburn"),
    ("BR", "São Paulo"), ("SG", "Singapore"), ("JP", "Tokyo"),
    ("DE", "Frankfurt"), ("SE", "Stockholm"), ("IN", "Mumbai"),
    ("ZA", "Johannesburg"),
]
UA = {"Content-Type": "application/json", "User-Agent": "open-tutor-bench/0.1"}

def api(method, path, body=None, retries=25):
    for attempt in range(retries):
        req = urllib.request.Request("https://api.globalping.io/v1" + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=UA, method=method)
        try:
            return json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                print(f"429 on {method} {path}, sleeping 180s (try {attempt+1}/{retries})", flush=True)
                time.sleep(180)
                continue
            raise

def create(city, backend):
    host = BASE.split("://", 1)[1].split("/", 1)[0]
    # Backend as a path segment: some probes percent-encode "?" in path.
    path = "/" + BASE.split("://", 1)[1].split("/", 1)[1] + f"/bench/{backend}"
    b = {"type": "http", "target": host,
         "locations": [{"country": city[0], "city": city[1], "limit": 5}],
         "measurementOptions": {"request": {"method": "GET", "path": path}}}
    return api("POST", "/measurements", b)["id"]

def wait(mid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(8)
        m = api("GET", f"/measurements/{mid}")
        if m.get("status") == "finished":
            return m
    return m

def tallies():
    import collections
    have = collections.Counter()
    try:
        for l in open("global-results.jsonl"):
            try:
                r = json.loads(l)
            except Exception:
                continue
            w = r.get("worker", {})
            if isinstance(w, dict) and w.get("ttft_ms"):
                have[(r.get("city"), r.get("backend"))] += 1
    except FileNotFoundError:
        pass
    return have


def main():
    out = open("global-results.jsonl", "a")
    have = tallies()
    for country, city in CITIES:
        for block, backend in enumerate(("a", "b", "c", "a", "b", "c")):
            target = 5 if block < 3 else 10  # first pass fills 0-5, second 5-10
            if have.get((city, backend), 0) >= target:
                print(f"{city} {backend}: already have {have[(city, backend)]}, skipping block", flush=True)
                continue
            try:
                mid = create((country, city), backend)
                m = wait(mid)
                for res in m.get("results", []):
                    p = res.get("probe", {})
                    r = res.get("result", {})
                    try:
                        body = json.loads(r.get("rawBody", ""))
                    except Exception:
                        body = {"raw": (r.get("rawBody", "")[:200])}
                    rec = {"city": p.get("city"), "country": p.get("country"),
                           "backend": backend, "status": r.get("status"),
                           "client_total_ms": (r.get("timings") or {}).get("total"),
                           "probe_cf_ray": (r.get("headers") or {}).get("cf-ray"),
                           "worker": body}
                    out.write(json.dumps(rec) + "\n")
                    out.flush()
                    w = body if isinstance(body, dict) else {}
                    print(f"{city} {backend}: ttft={w.get('ttft_ms')} total={w.get('total_ms')} "
                          f"colo={w.get('colo')} client={rec['client_total_ms']} rc={w.get('reasoning_chars')}",
                          flush=True)
            except Exception as e:
                print(f"{city} {backend}: ERROR {str(e)[:150]}", flush=True)
                time.sleep(10)

if __name__ == "__main__":
    main()
