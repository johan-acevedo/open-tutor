# Skolverket Syllabus lookup

Read-only agent tool for Skolverket's open Syllabus API: curricula, subjects and
courses/levels with central content, assessment criteria and SKOLFS source data.
Covers Lgr22 grundskola (`GR…` codes, e.g. `GRGRMAT01`) and gymnasiet Gy11
(`MAT`, `KEM`, `SAM`) + Gy25 (`MATE`, `KEMI`). Stdlib only, JSON output.

Full usage, code table and verified live examples live in
`tools/skolverket/README.md` — start there.

## Quick recipes

```bash
python3 tools/skolverket/skolverket.py --format summary school-types
python3 tools/skolverket/skolverket.py --format summary curriculums
python3 tools/skolverket/skolverket.py --format summary subjects --schooltype GR --query kemi
python3 tools/skolverket/skolverket.py --format summary subjects --schooltype GY --query matem
python3 tools/skolverket/skolverket.py subject GRGRMAT01 --format text
python3 tools/skolverket/skolverket.py subject MATE --format summary
python3 tools/skolverket/skolverket.py course KEMI1000X --format text
```

Rules: default `--api v1` (stable); `--format json` returns the full live
response, never truncated; `--format summary` keeps SKOLFS/version/source links;
`--query` is a case-/accent-insensitive Swedish substring over name + code.
Generation (GY11 vs GY25) is on detail calls (`reform`, `startDate`/`endDate`),
not in list views. Unknown code → exit 1 with a hint; empty search → exit 3.
Docs: https://api.skolverket.se/syllabus/swagger-ui/index.html
