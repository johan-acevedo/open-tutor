#!/usr/bin/env python3
"""Read-only lookup client for Skolverket's Syllabus API (open data).

Covers curricula (läroplaner), subjects (ämnen) and courses/levels (kurser/nivåer)
for Lgr22 (grundskolan, schooltype GR) and gymnasiet Gy11/Gy25 (schooltype GY).

Live OpenAPI documents (inspected 2026-11-12, do not guess other paths):
  stable v1 (active 1.16.x): https://api.skolverket.se/syllabus/v3/api-docs
  alpha  v2 (2.0.0):         https://api.skolverket.se/syllabus/v3/api-docs-v2/{subjects,courses,...}

Base URL for data: https://api.skolverket.se/syllabus  (paths /v1/... or /v2/...)
Swagger UI:        https://api.skolverket.se/syllabus/swagger-ui/index.html

This tool is READ-ONLY: it only performs HTTP GET requests. There is no
application integration, no web server and no MCP infrastructure here.

Stdlib only. Default output is the full live JSON response (never truncated).
Use --format summary|text for compact overviews or plain-text reading.
"""

from __future__ import annotations

import argparse
import hashlib
import html as htmlmod
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

DEFAULT_BASE = "https://api.skolverket.se/syllabus"
SWAGGER_UI = "https://api.skolverket.se/syllabus/swagger-ui/index.html"
API_DOCS = "https://www.skolverket.se/om-oss/oppna-data/api-for-laroplaner-kurs--och-amnesplaner-syllabus"
DEFAULT_TIMEOUT = 30
DEFAULT_TTL = 24 * 3600  # cache time-to-live, seconds

VERSION = "1.0.0"


class SkolverketError(Exception):
    """Fatal lookup error with a human-readable message and exit code."""

    def __init__(self, message: str, *, hint: str = "", exit_code: int = 1):
        super().__init__(message)
        self.hint = hint
        self.exit_code = exit_code


# --------------------------------------------------------------------------
# plain-text rendering of the HTML fields the API returns
# --------------------------------------------------------------------------

_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "br", "ul", "ol"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = htmlmod.unescape(raw)
        lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in raw.splitlines()]
        out: list[str] = []
        for ln in lines:
            if ln:
                out.append(ln)
            elif out and out[-1] != "":
                out.append("")
        return "\n".join(out).strip()


def html_to_text(value: Any) -> Any:
    """Convert an HTML string (or {"text": html, ...} object) to plain text."""
    if isinstance(value, dict) and "text" in value:
        return html_to_text(value["text"])
    if isinstance(value, str):
        parser = _TextExtractor()
        parser.feed(value)
        return parser.text()
    if isinstance(value, list):
        return [html_to_text(v) for v in value]
    return value


def _norm(text: str) -> str:
    """Case- and accent-insensitive normalisation for Swedish name matching."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


# --------------------------------------------------------------------------
# HTTP client with a small file cache
# --------------------------------------------------------------------------

def _cache_path(cache_dir: str, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return os.path.join(cache_dir, digest + ".json")


class Client:
    def __init__(
        self,
        base: str = DEFAULT_BASE,
        api: str = "v1",
        timeout: int = DEFAULT_TIMEOUT,
        cache_dir: str | None = None,
        cache_ttl: int = DEFAULT_TTL,
        no_cache: bool = False,
    ) -> None:
        self.base = base.rstrip("/")
        self.api = api.strip("/")
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        if cache_dir is None:
            root = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
            cache_dir = os.path.join(root, "skolverket-syllabus")
        self.cache_dir = cache_dir if not no_cache else None

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        url = f"{self.base}/{self.api}{path}"
        query = {k: v for k, v in (params or {}).items() if v is not None}
        if query:
            url += "?" + urllib.parse.urlencode(query)
        return url

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON document. Returns the full parsed response, never truncated."""
        url = self._url(path, params)
        cached_load_error: str | None = None
        if self.cache_dir:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                p = _cache_path(self.cache_dir, url)
                if os.path.exists(p) and time.time() - os.path.getmtime(p) < self.cache_ttl:
                    with open(p, encoding="utf-8") as fh:
                        return json.load(fh)
            except (OSError, ValueError) as exc:  # corrupt cache: refetch live
                cached_load_error = str(exc)
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": f"open-tutor-skolverket/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            hint = ""
            if exc.code == 404:
                hint = "Unknown code. List valid codes, e.g. `subjects --schooltype GY` or `courses --schooltype GY`."
            raise SkolverketError(f"HTTP {exc.code} for {url}", hint=hint)
        except urllib.error.URLError as exc:
            raise SkolverketError(f"Network error for {url}: {exc.reason}", hint="Check network access, then retry.")
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise SkolverketError(f"Bad response from {url}: {exc}")
        if self.cache_dir:
            try:
                with open(_cache_path(self.cache_dir, url), "w", encoding="utf-8") as fh:
                    json.dump(data, fh, ensure_ascii=False)
            except OSError:
                pass  # cache is best-effort; live data was already returned
        _ = cached_load_error
        return data

    # -- valuestore ------------------------------------------------------
    def school_types(self, expired: bool = False) -> dict[str, Any]:
        return self.get("/valuestore/schooltypes/expired" if expired else "/valuestore/schooltypes")

    def typeofsyllabus(self) -> dict[str, Any]:
        return self.get("/valuestore/typeofsyllabus")

    def subject_and_course_codes(self) -> dict[str, Any]:
        return self.get("/valuestore/subjectandcoursecodes")

    def studypathcodes(self, **params: Any) -> dict[str, Any]:
        return self.get("/valuestore/studypathcodes", params or None)

    # -- curriculums -----------------------------------------------------
    def curriculums(self, schooltype: str | None = None, timespan: str | None = None,
                    date: str | None = None) -> dict[str, Any]:
        key = "schoolType" if self.api == "v2" else "schooltype"
        return self.get("/curriculums", {key: schooltype, "timespan" if self.api == "v1" else "timeSpan": timespan, "date": date})

    def curriculum(self, code: str, date: str | None = None) -> dict[str, Any]:
        return self.get(f"/curriculums/{code}", {"date": date})

    def curriculum_versions(self, code: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/curriculums/{code}/versions", params or None)

    def curriculum_version(self, code: str, version: str) -> dict[str, Any]:
        return self.get(f"/curriculums/{code}/versions/{version}")

    # -- subjects --------------------------------------------------------
    def subjects(self, schooltype: str | None = None, timespan: str | None = None,
                 type_of_syllabus: str | None = None, date: str | None = None) -> dict[str, Any]:
        key = "schoolType" if self.api == "v2" else "schooltype"
        return self.get("/subjects", {
            key: schooltype,
            "timespan" if self.api == "v1" else "timeSpan": timespan,
            "typeOfSyllabus": type_of_syllabus,
            "date": date,
        })

    def subject(self, code: str, date: str | None = None) -> dict[str, Any]:
        return self.get(f"/subjects/{code}", {"date": date})

    def subject_versions(self, code: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/subjects/{code}/versions", params or None)

    def subject_version(self, code: str, version: str) -> dict[str, Any]:
        return self.get(f"/subjects/{code}/versions/{version}")

    # -- courses ---------------------------------------------------------
    def courses(self, schooltype: str | None = None, timespan: str | None = None,
                date: str | None = None) -> dict[str, Any]:
        key = "schoolType" if self.api == "v2" else "schooltype"
        return self.get("/courses", {
            key: schooltype,
            "timespan" if self.api == "v1" else "timeSpan": timespan,
            "date": date,
        })

    def course(self, code: str) -> dict[str, Any]:
        return self.get(f"/courses/{code}")

    def course_versions(self, code: str) -> dict[str, Any]:
        return self.get(f"/courses/{code}/versions")

    def course_version(self, code: str, version: str) -> dict[str, Any]:
        return self.get(f"/courses/{code}/versions/{version}")

    # -- programs --------------------------------------------------------
    def programs(self, **params: Any) -> dict[str, Any]:
        return self.get("/programs", params or None)

    def program(self, code: str, **params: Any) -> dict[str, Any]:
        return self.get(f"/programs/{code}", params or None)

    def api_info(self) -> dict[str, Any]:
        return self.get("/api-info")


# --------------------------------------------------------------------------
# summaries: compact agent-friendly views (source/version links preserved)
# --------------------------------------------------------------------------

def _source_links(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "skolfsGrund": entity.get("skolfsGrund"),
        "skolfsAndring": entity.get("skolfsAndring"),
        "canceledSkolfs": entity.get("canceledSkolfs"),
        "startDate": entity.get("startDate"),
        "endDate": entity.get("endDate"),
        "modifiedDate": entity.get("modifiedDate"),
        "versionInfo": entity.get("versionInfo"),
    }


def summarize_list(doc: dict[str, Any], items_key: str) -> dict[str, Any]:
    items = doc.get(items_key, []) or []
    return {
        "totalElements": doc.get("totalElements", len(items)),
        "items": [
            {
                "code": _code_of(it),
                "name": _name_of(it),
                "version": it.get("version"),
                "schoolTypes": it.get("schoolTypes"),
                "reform": it.get("reform"),
                "typeOfSyllabus": it.get("typeOfSyllabus"),
                "startDate": it.get("startDate"),
                "endDate": it.get("endDate"),
            }
            for it in items
        ],
        "_source": {
            "apiName": doc.get("apiName"),
            "apiVersion": doc.get("apiVersion"),
            "apiStatus": doc.get("apiStatus"),
            "apiDocumentation": doc.get("apiDocumentation", API_DOCS),
        },
    }


def _rich_text_len(value: Any) -> int:
    if isinstance(value, dict) and "text" in value:
        return len(value.get("text") or "")
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_rich_text_len(v) for v in value)
    return 0


def summarize_subject(doc: dict[str, Any]) -> dict[str, Any]:
    s = doc.get("subject", {})
    courses = s.get("courses", []) or []
    central = s.get("centralContents")
    criteria = s.get("knowledgeRequirements")
    return {
        "code": s.get("code"),
        "name": s.get("name"),
        "englishName": s.get("englishName"),
        "version": s.get("version"),
        "reform": s.get("reform"),
        "typeOfSyllabus": s.get("typeOfSyllabus"),
        "schoolTypes": s.get("schoolTypes"),
        "gradeScale": s.get("gradeScale"),
        "designation": s.get("designation"),
        "purposeHeading": html_to_text(s.get("purposeHeading")),
        "purpose": html_to_text(s.get("purpose")),
        "purposeChars": _rich_text_len(s.get("purpose")),
        "centralContentBlocks": len(central) if isinstance(central, list) else (1 if central else 0),
        "centralContentChars": _rich_text_len(central),
        "knowledgeRequirementBlocks": len(criteria) if isinstance(criteria, list) else (1 if criteria else 0),
        "knowledgeRequirementsChars": _rich_text_len(criteria),
        "courses": [
            {"code": c.get("code"), "name": c.get("name"), "points": c.get("points")}
            for c in courses
        ],
        "source": _source_links(s),
        "_api": {
            "apiVersion": doc.get("apiVersion"),
            "apiDocumentation": doc.get("apiDocumentation", API_DOCS),
        },
        "_note": "Full text available with `--format json` (raw) or `--format text`. Nothing was truncated.",
    }


def summarize_course(doc: dict[str, Any]) -> dict[str, Any]:
    c = doc.get("course", {})
    central = c.get("centralContent")
    criteria = c.get("knowledgeRequirements")
    parent = c.get("subjectParent") or {}
    return {
        "code": c.get("code"),
        "name": c.get("name"),
        "points": c.get("points"),
        "typeOfSyllabus": c.get("typeOfSyllabus"),
        "subjectParent": {k: parent.get(k) for k in ("code", "name")},
        "centralContentChars": _rich_text_len(central),
        "knowledgeRequirementsChars": _rich_text_len(criteria),
        "source": _source_links(c),
        "_api": {
            "apiVersion": doc.get("apiVersion"),
            "apiDocumentation": doc.get("apiDocumentation", API_DOCS),
        },
        "_note": "Full text available with `--format json` (raw) or `--format text`. Nothing was truncated.",
    }


def render_text_subject(doc: dict[str, Any]) -> str:
    s = doc.get("subject", {})
    lines = [
        f"{s.get('name')} ({s.get('code')})  version {s.get('version')}"
        + (f"  reform {s.get('reform')}" if s.get("reform") else ""),
        f"School types: {', '.join(s.get('schoolTypes') or [])}  |  SKOLFS grund: {s.get('skolfsGrund')}  ändring: {s.get('skolfsAndring')}",
        "",
        "== Syfte ==",
        str(html_to_text(s.get("purpose")) or "(no purpose text)"),
    ]
    central = s.get("centralContents")
    if central:
        blocks = central if isinstance(central, list) else [central]
        lines.append("")
        lines.append("== Centralt innehåll ==")
        for b in blocks:
            lines.append(str(html_to_text(b)))
            lines.append("")
    criteria = s.get("knowledgeRequirements")
    if criteria:
        blocks = criteria if isinstance(criteria, list) else [criteria]
        lines.append("== Kriterier / betygskriterier ==")
        for b in blocks:
            lines.append(str(html_to_text(b)))
            lines.append("")
    courses = s.get("courses") or []
    if courses:
        lines.append("== Kurser / nivåer ==")
        for c in courses:
            lines.append(f"- {c.get('code')}: {c.get('name')}" + (f" ({c.get('points')}p)" if c.get("points") else ""))
    return "\n".join(lines).strip() + "\n"


def render_text_course(doc: dict[str, Any]) -> str:
    c = doc.get("course", {})
    lines = [
        f"{c.get('name')} ({c.get('code')})" + (f"  {c.get('points')}p" if c.get("points") else ""),
        "",
        "== Centralt innehåll ==",
        str(html_to_text(c.get("centralContent")) or "(none)"),
        "",
        "== Kriterier / betygskriterier ==",
        str(html_to_text(c.get("knowledgeRequirements")) or "(none)"),
    ]
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------
# client-side find (works on both v1 and v2 list payloads)
# --------------------------------------------------------------------------

def _code_of(item: dict[str, Any]) -> str:
    # subject/curriculum lists use code+name; course lists use courseCode+courseName
    return str(item.get("code") or item.get("courseCode") or item.get("subjectCode") or "")


def _name_of(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("courseName") or item.get("subjectName") or "")


def find_in_list(doc: dict[str, Any], items_key: str, query: str) -> list[dict[str, Any]]:
    q = _norm(query.strip())
    if not q:
        return []
    hits = []
    for it in doc.get(items_key, []) or []:
        hay = _norm(f"{_code_of(it)} {_name_of(it)} {it.get('englishName', '')}")
        if q in hay:
            hits.append(it)
    return hits


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _add_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--base", default=DEFAULT_BASE, help=f"API base URL (default {DEFAULT_BASE})")
    sp.add_argument("--api", choices=["v1", "v2"], default="v1",
                    help="API generation: v1 is stable/active, v2 is alpha (default v1)")
    sp.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    sp.add_argument("--cache-dir", default=None, help="JSON cache directory (default ~/.cache/skolverket-syllabus)")
    sp.add_argument("--no-cache", action="store_true")
    sp.add_argument("--cache-ttl", type=int, default=DEFAULT_TTL)
    sp.add_argument("--refresh", action="store_true", help="Bypass cache for this call (still writes cache)")
    sp.add_argument("--format", choices=["json", "summary", "text"], default="json",
                    help="json: full live response; summary: compact JSON overview; text: plain-text reading view")
    sp.add_argument("--out", default=None, help="Write output to FILE as well as stdout")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skolverket", description="Read-only lookup for Skolverket Syllabus API (open data).")
    _add_common(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("school-types", help="List school types (GR, GY, ...).")
    p.add_argument("--expired", action="store_true")

    p = sub.add_parser("typeofsyllabus", help="List syllabus types.")
    p = sub.add_parser("subject-codes", help="List subject/course codes (valuestore).")
    p = sub.add_parser("studypath-codes", help="List study-path codes.")
    p.add_argument("--schooltype")

    p = sub.add_parser("curriculums", help="List curricula (Lgr22, Gy11, Gy25, ...).")
    p.add_argument("--schooltype")
    p.add_argument("--timespan")
    p.add_argument("--date")

    p = sub.add_parser("curriculum", help="Read one curriculum.")
    p.add_argument("code")
    p.add_argument("--date")
    p.add_argument("--versions", action="store_true")
    p.add_argument("--version")

    p = sub.add_parser("subjects", help="List subjects, optionally filtered by Swedish name/code.")
    p.add_argument("--schooltype", help="E.g. GR (grundskolan/Lgr22), GY (gymnasiet).")
    p.add_argument("--timespan")
    p.add_argument("--type", dest="type_of_syllabus")
    p.add_argument("--date")
    p.add_argument("--query", help="Case-insensitive substring match on Swedish name/code, e.g. 'kemi'.")

    p = sub.add_parser("subject", help="Read one subject with central content, criteria, courses, source data.")
    p.add_argument("code", help="E.g. GRGRMAT01, GRGRKEM01, GRGRSAM01 (Lgr22) or MAT/MATE, KEM/KEMI (Gy11/Gy25).")
    p.add_argument("--date")
    p.add_argument("--versions", action="store_true")
    p.add_argument("--version")

    p = sub.add_parser("courses", help="List courses/levels, optionally filtered by Swedish name/code.")
    p.add_argument("--schooltype")
    p.add_argument("--timespan")
    p.add_argument("--date")
    p.add_argument("--query")

    p = sub.add_parser("course", help="Read one course/level with central content and criteria.")
    p.add_argument("code", help="E.g. MATMAT01a (Gy11) or MATE1A00X (Gy25).")
    p.add_argument("--versions", action="store_true")
    p.add_argument("--version")

    p = sub.add_parser("programs", help="List programs.")
    p.add_argument("--schooltype")
    p.add_argument("--timespan")
    p.add_argument("--date")

    p = sub.add_parser("program", help="Read one program.")
    p.add_argument("code")

    p = sub.add_parser("api-info", help="Show API version/status.")
    return ap


def _filter_query(doc: dict[str, Any], key: str, query: str | None, singular: str) -> dict[str, Any]:
    if not query:
        return doc
    hits = find_in_list(doc, key, query)
    if not hits:
        raise SkolverketError(
            f"No {singular} matching {query!r} (total searched: {doc.get('totalElements', len(doc.get(key, [])))})",
            hint="Try a shorter Swedish fragment (e.g. 'matem', 'kemi', 'samh') or list all with --schooltype.",
            exit_code=3,
        )
    out = dict(doc)
    out[key] = hits
    out["totalElements"] = len(hits)
    out["queryParam"] = query
    return out


_GLOBAL_FLAGS_WITH_VALUE = {"--base", "--api", "--timeout", "--cache-dir", "--cache-ttl", "--format", "--out"}
_GLOBAL_FLAGS_BARE = {"--no-cache", "--refresh"}
_SUBCOMMANDS = {"school-types", "typeofsyllabus", "subject-codes", "studypath-codes",
                  "curriculums", "curriculum", "subjects", "subject", "courses", "course",
                  "programs", "program", "api-info"}


def _hoist_global_flags(argv: list[str]) -> list[str]:
    """Allow global flags after the subcommand: move them before it."""
    idx = next((i for i, t in enumerate(argv) if t in _SUBCOMMANDS), None)
    if idx is None:
        return argv
    head, tail = argv[:idx], argv[idx + 1:]
    hoisted: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(tail):
        tok = tail[i]
        if tok in _GLOBAL_FLAGS_WITH_VALUE:
            hoisted += tail[i:i + 2]
            i += 2
        elif tok in _GLOBAL_FLAGS_BARE:
            hoisted.append(tok)
            i += 1
        elif tok.startswith("--") and "=" in tok and tok.split("=", 1)[0] in _GLOBAL_FLAGS_WITH_VALUE:
            hoisted.append(tok)
            i += 1
        else:
            rest.append(tok)
            i += 1
    return head + hoisted + [argv[idx]] + rest


def run(argv: list[str] | None = None) -> int:
    ap = build_parser()
    ns = ap.parse_args(_hoist_global_flags(list(argv) if argv is not None else sys.argv[1:]))
    client = Client(base=ns.base, api=ns.api, timeout=ns.timeout,
                    cache_dir=ns.cache_dir, cache_ttl=0 if ns.refresh else ns.cache_ttl,
                    no_cache=ns.no_cache)
    try:
        cmd = ns.cmd
        if cmd == "school-types":
            doc = client.school_types(expired=ns.expired)
            payload: Any = doc if ns.format == "json" else summarize_list(doc, "schoolTypes")
        elif cmd == "typeofsyllabus":
            doc = client.typeofsyllabus()
            payload = doc if ns.format == "json" else summarize_list(doc, "typeOfSyllabusList")
        elif cmd == "subject-codes":
            doc = client.subject_and_course_codes()
            payload = doc
        elif cmd == "studypath-codes":
            key = "schoolType" if ns.api == "v2" else "schooltype"
            doc = client.studypathcodes(**{key: getattr(ns, "schooltype", None)})
            payload = doc
        elif cmd == "curriculums":
            doc = client.curriculums(schooltype=ns.schooltype, timespan=ns.timespan, date=ns.date)
            payload = doc if ns.format == "json" else summarize_list(doc, "curriculums")
        elif cmd == "curriculum":
            if ns.versions:
                doc = client.curriculum_versions(ns.code)
                payload = doc if ns.format == "json" else summarize_list(doc, "curriculums")
            elif ns.version:
                doc = client.curriculum_version(ns.code, ns.version)
                payload = doc
            else:
                doc = client.curriculum(ns.code, date=ns.date)
                payload = doc
        elif cmd == "subjects":
            doc = client.subjects(schooltype=ns.schooltype, timespan=ns.timespan,
                                  type_of_syllabus=ns.type_of_syllabus, date=ns.date)
            doc = _filter_query(doc, "subjects", ns.query, "subjects")
            payload = doc if ns.format == "json" else summarize_list(doc, "subjects")
        elif cmd == "subject":
            if ns.versions:
                doc = client.subject_versions(ns.code)
                payload = doc if ns.format == "json" else summarize_list(doc, "subjects")
            elif ns.version:
                doc = client.subject_version(ns.code, ns.version)
                payload = _format_detail(doc, "subject", ns.format)
            else:
                doc = client.subject(ns.code, date=ns.date)
                payload = _format_detail(doc, "subject", ns.format)
        elif cmd == "courses":
            doc = client.courses(schooltype=ns.schooltype, timespan=ns.timespan, date=ns.date)
            doc = _filter_query(doc, "courses", ns.query, "courses")
            payload = doc if ns.format == "json" else summarize_list(doc, "courses")
        elif cmd == "course":
            if ns.versions:
                doc = client.course_versions(ns.code)
                payload = doc if ns.format == "json" else summarize_list(doc, "courses")
            elif ns.version:
                doc = client.course_version(ns.code, ns.version)
                payload = _format_detail(doc, "course", ns.format)
            else:
                doc = client.course(ns.code)
                payload = _format_detail(doc, "course", ns.format)
        elif cmd == "programs":
            key = "schoolType" if ns.api == "v2" else "schooltype"
            ts = "timeSpan" if ns.api == "v2" else "timespan"
            doc = client.programs(**{key: ns.schooltype, ts: ns.timespan, "date": ns.date})
            payload = doc if ns.format == "json" else summarize_list(doc, "programs")
        elif cmd == "program":
            doc = client.program(ns.code)
            payload = doc
        elif cmd == "api-info":
            payload = client.api_info()
        else:
            ap.error(f"unknown command {cmd}")
    except SkolverketError as exc:
        err = {"error": str(exc)}
        if exc.hint:
            err["hint"] = exc.hint
        print(json.dumps(err, ensure_ascii=False, indent=2), file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:
        return 0

    if ns.format == "text" and isinstance(payload, str):
        output = payload
    else:
        output = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(output)
    except BrokenPipeError:
        return 0
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as fh:
            fh.write(output)
    return 0


def _format_detail(doc: dict[str, Any], kind: str, fmt: str) -> Any:
    if fmt == "json":
        return doc
    if fmt == "summary":
        return summarize_subject(doc) if kind == "subject" else summarize_course(doc)
    if kind == "subject":
        return render_text_subject(doc)
    return render_text_course(doc)


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
