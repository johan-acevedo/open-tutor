# Skolverket Syllabus lookup (read-only, agent-facing)

Small stdlib-only Python CLI/library for Skolverket's open Syllabus API
(curricula, subjects, courses/levels). Built for agents that need ground truth
about Swedish school content: what a subject covers, its central content
(centralt innehåll), assessment criteria, version/SKOLFS source data.

- Live API docs (inspected 2026-11-12, paths below are real, not guessed):
  Swagger UI: https://api.skolverket.se/syllabus/swagger-ui/index.html
  OpenAPI v1 (stable/active 1.16.x): https://api.skolverket.se/syllabus/v3/api-docs
  OpenAPI v2 groups (alpha 2.0.0):  https://api.skolverket.se/syllabus/v3/api-docs-v2/{subjects,courses,programs,curriculums,valuestore,search,...}
- Base URL: `https://api.skolverket.se/syllabus`, data paths `/v1/...` (default, stable) or `/v2/...` (`--api v2`, alpha).
- This tool only does HTTP GET. It runs independently of the tutor application.

## Use

```bash
python3 tools/skolverket/skolverket.py --help
```

Global flags (accepted before or after the command): `--api v1|v2` (default v1),
`--format json|summary|text` (default json = full live response, never truncated),
`--out FILE`, `--no-cache` / `--refresh`, `--cache-dir`, `--timeout`.

Discover school types and curricula:

```bash
python3 tools/skolverket/skolverket.py --format summary school-types
python3 tools/skolverket/skolverket.py --format summary curriculums
```

Find subjects by Swedish name or code (`--query` is a case-/accent-insensitive
substring over name + code; it searches the returned list client-side):

```bash
python3 tools/skolverket/skolverket.py --format summary subjects --schooltype GR --query kemi
python3 tools/skolverket/skolverket.py --format summary subjects --schooltype GY --query matem
python3 tools/skolverket/skolverket.py --format summary courses --schooltype GY --query "matematik 1a"
```

Read full subject/course content (purpose, central content, criteria, courses,
SKOLFS/version/source dates):

```bash
python3 tools/skolverket/skolverket.py subject GRGRMAT01 --format text     # Lgr22 maths, plain text
python3 tools/skolverket/skolverket.py subject MATE --format summary      # Gy25 maths, overview + source links
python3 tools/skolverket/skolverket.py course KEMKEM01                     # Gy11 Kemi 1, full JSON
python3 tools/skolverket/skolverket.py subject MAT --versions --format summary
```

As a library:

```python
import sys; sys.path.insert(0, "tools/skolverket")
from skolverket import Client, find_in_list
c = Client()  # v1 stable; Client(api="v2") for alpha
doc = c.subject("GRGRSAM01")          # full JSON, untruncated
hits = find_in_list(c.subjects(schooltype="GY"), "subjects", "kemi")
```

## What the codes mean (verified live 2026-11-12)

| Level | Subject code | Generation | Shape |
|---|---|---|---|
| Grundskolan (Lgr22, `GR`) | `GRGRMAT01` Matematik, `GRGRKEM01` Kemi, `GRGRSAM01` Samhällskunskap, `GRGRHIS01` Historia, ... (27 subjects, v14) | Lgr22 | `COURSE_SYLLABUS`: central content + criteria inline, no `courses` list |
| Gymnasiet Gy11 | `MAT` Matematik (v11, 11 courses), `KEM` Kemi (v2), `SAM` Samhällskunskap (v4), ... | `reform: GY11`, `typeOfSyllabus: SUBJECT_SYLLABUS` | purpose on subject; central content + criteria per course (`MATMAT01a`, `KEMKEM01`, ...) |
| Gymnasiet Gy25 | `MATE` Matematik (v1, 6 nivåer), `KEMI` Kemi (v2), ... | `reform: GY25`, `typeOfSyllabus: GRADE_SUBJECT_SYLLABUS` | criteria on subject; central content per nivå (`MATE1A00X`, `KEMI1000X`, ...) |

Curricula: `LGR22` (grundskolan), `GY2011` (gymnasiet, still current for running
cohorts), `LGY2025` (gymnasiet from 2025-08-01). Gy11 subjects carry
`endDate: 2030-06-30` (teach-out); Generation is explicit only on detail calls
(`reform`, `startDate`/`endDate`) and versions — the list view shows
code/name/version only, so old and new generations appear side by side there
(e.g. `MAT` next to `MATE`).

Source links preserved in `--format summary`: `skolfsGrund` / `skolfsAndring`
(e.g. `2010:37` / `2022:8`), `startDate`, `endDate`, `modifiedDate`,
`versionInfo`, plus `apiDocumentation`. Full raw JSON is always one flag away.

## Verified live 2026-11-12 (exact commands → results)

- `school-types --format summary` → 24 types incl. `GR Grundskola`, `GY Gymnasieskola`.
- `curriculums --format summary` → 10 curricula incl. `LGR22`, `GY2011`, `LGY2025`.
- `subject GRGRMAT01 --format summary` → Matematik v14, 3 central-content blocks
  (8882 chars), 11 criteria blocks (10415 chars), SKOLFS `2010:37`/`2022:8`.
- `subject GRGRKEM01` → v14; `subject GRGRSAM01` → v14 (8737 central chars);
  `subject GRGRHIS01` → v14 (7849 central chars).
- `subject MAT` → reform GY11, 11 courses (`MATMAT01a`…); `subject MATE` →
  reform GY25, 6 nivåer (`MATE1A00X`…), criteria on subject (5 blocks).
- `course KEMKEM01` (Gy11 Kemi 1, 100p) and `course KEMI1000X` (Gy25 Nivå 1, 100p) both live.
- `subject SAM` → Gy11 Samhällskunskap v4, 7 courses; `subject MAT --versions` → 6 versions.
- Errors: unknown code → `{"error": "HTTP 404 ...", "hint": "Unknown code. List valid codes, ..."}` exit 1;
  bad host → `Network error ...` exit 1; empty `--query` hit → exit 3 with hint.
- Tests: `cd tools/skolverket && python3 -m unittest discover -s tests` → 20 tests OK
  (fake HTTP over captured live fixtures; no network).

## Limitations (honest)

- The v1 OpenAPI marks every path `deprecated: true`, but the API itself reports
  `apiStatus: active`, version `1.16.2-SNAPSHOT`, and serves full current data
  (Lgr22 + Gy11 + Gy25). v2 (`--api v2`) is explicitly `alpha`. Default stays v1.
- `--query` filters the returned list client-side; listing GY subjects returns
  ~880 items and GY courses ~2192 items (a few seconds, cached 24h by default).
  The server-side `/v2/search` endpoint (alpha) is deliberately not used.
- Course list items use `courseCode`/`courseName` keys while details use
  `code`/`name` — the tool normalises both, but raw `--format json` shows the
  live shapes as-is.
- Text fields are HTML in the source; `--format text` strips tags (stdlib parser).
  Swedish soft hyphens (U+00AD) from the source are kept as-is.
- No programs/vocational-packages convenience formatting yet (`programs`,
  `program` return raw JSON); versions/history via `--versions`/`--version`.
- Cache default `~/.cache/skolverket-syllabus`, TTL 24h; `--refresh`/`--no-cache`
  bypass it.
