"""Behavioral tests for tools/skolverket (stdlib unittest, no network).

All HTTP is faked: urllib.request.urlopen is mapped to captured live responses
in tests/fixtures (small, trimmed but real shapes from 2026-11-12).
"""

import io
import json
import os
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import skolverket
from skolverket import Client, SkolverketError, find_in_list, html_to_text, summarize_subject

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as fh:
        return json.load(fh)


# path -> fixture file (query strings stripped)
ROUTES = {
    "/syllabus/v1/valuestore/schooltypes": "schooltypes.json",
    "/syllabus/v1/curriculums": "curriculums.json",
    "/syllabus/v1/subjects": "subjects_gr.json",
    "/syllabus/v1/subjects/GRGRMAT01": "subject_GRGRMAT01.json",
    "/syllabus/v1/subjects/MAT": "subject_MAT.json",
    "/syllabus/v1/subjects/MATE": "subject_MATE.json",
    "/syllabus/v1/subjects/KEM": "subject_KEM.json",
    "/syllabus/v1/subjects/KEMI": "subject_KEMI.json",
    "/syllabus/v1/subjects/SAM": "subject_SAM.json",
    "/syllabus/v1/subjects/MAT/versions": "versions_MAT.json",
    "/syllabus/v1/courses/MATMAT01a": "course_MATMAT01a.json",
    "/syllabus/v1/courses/MATE1A00X": "course_MATE1A00X.json",
    "/syllabus/v1/courses/KEMKEM01": "course_KEMKEM01.json",
    "/syllabus/v1/api-info": "api_info.json",
}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeHTTP:
    """urlopen replacement serving fixtures; records requested URLs."""

    def __init__(self, test):
        self.test = test
        self.urls: list[str] = []

    def __call__(self, req, timeout=None):
        from urllib.parse import urlsplit

        url = req.full_url if hasattr(req, "full_url") else req
        self.urls.append(url)
        path = urlsplit(url).path
        if path not in ROUTES:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b"{}"))
        return FakeResponse(load(ROUTES[path]))


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.http = FakeHTTP(self)
        self._real = skolverket.urllib.request.urlopen
        skolverket.urllib.request.urlopen = self.http

    def tearDown(self):
        skolverket.urllib.request.urlopen = self._real

    def client(self):
        return Client(cache_dir=None, no_cache=True)

    # -- discovery -----------------------------------------------------
    def test_school_types_lists_gr_and_gy(self):
        doc = self.client().school_types()
        codes = {s["code"]: s["name"] for s in doc["schoolTypes"]}
        self.assertEqual(codes["GR"], "Grundskola")
        self.assertEqual(codes["GY"], "Gymnasieskola")

    def test_curriculums_include_lgr22(self):
        doc = self.client().curriculums()
        codes = {c["code"] for c in doc["curriculums"]}
        self.assertIn("LGR22", codes)

    # -- find by Swedish name/code --------------------------------------
    def test_find_subject_by_swedish_name(self):
        doc = load("subjects_gr.json")
        hits = find_in_list(doc, "subjects", "kemi")
        self.assertEqual([h["code"] for h in hits], ["GRGRKEM01"])

    def test_find_subject_by_code_fragment_case_insensitive(self):
        doc = load("subjects_gr.json")
        hits = find_in_list(doc, "subjects", "grgrmat")
        self.assertEqual([h["code"] for h in hits], ["GRGRMAT01"])
        hits = find_in_list(doc, "subjects", "SAMHÄLLSKUNSKAP")
        self.assertEqual([h["code"] for h in hits], ["GRGRSAM01"])

    def test_find_no_match_returns_empty(self):
        self.assertEqual(find_in_list(load("subjects_gr.json"), "subjects", "xyzzy"), [])

    def test_find_course_by_name_with_course_keys(self):
        doc = {"courses": [{"courseCode": "MATMAT01a", "courseName": "Matematik 1a"}]}
        hits = find_in_list(doc, "courses", "matematik 1a")
        self.assertEqual(len(hits), 1)

    def test_global_flags_work_after_subcommand(self):
        code, out, _ = self.run_cli("subject", "MATE", "--format", "summary")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["reform"], "GY25")

    # -- subject content: Lgr22 vs Gy11 vs Gy25 --------------------------
    def test_lgr22_subject_has_central_content_and_criteria(self):
        doc = self.client().subject("GRGRMAT01")
        s = doc["subject"]
        self.assertTrue(s["centralContents"], "Lgr22 subject must carry central content")
        self.assertTrue(s["knowledgeRequirements"], "Lgr22 subject must carry criteria")
        self.assertEqual(s.get("courses") or [], [])

    def test_gy11_subject_lists_courses(self):
        doc = self.client().subject("MAT")
        s = doc["subject"]
        self.assertEqual(s["reform"], "GY11")
        self.assertEqual(s["typeOfSyllabus"], "SUBJECT_SYLLABUS")
        codes = [c["code"] for c in s["courses"]]
        self.assertIn("MATMAT01a", codes)

    def test_gy25_subject_lists_levels(self):
        doc = self.client().subject("MATE")
        s = doc["subject"]
        self.assertEqual(s["reform"], "GY25")
        self.assertEqual(s["typeOfSyllabus"], "GRADE_SUBJECT_SYLLABUS")
        codes = [c["code"] for c in s["courses"]]
        self.assertIn("MATE1A00X", codes)

    def test_gy25_kemi_levels(self):
        doc = self.client().subject("KEMI")
        self.assertEqual(doc["subject"]["reform"], "GY25")

    def test_course_has_central_content(self):
        doc = self.client().course("MATMAT01a")
        text = doc["course"]["centralContent"]["text"]
        self.assertIn("centrala inneh", text)

    # -- summaries preserve source/version links -------------------------
    def test_subject_summary_keeps_source_links(self):
        summ = summarize_subject(load("subject_MAT.json"))
        self.assertEqual(summ["code"], "MAT")
        self.assertEqual(summ["reform"], "GY11")
        src = summ["source"]
        self.assertTrue(src["skolfsGrund"], "SKOLFS source link must survive")
        self.assertTrue(src["startDate"])
        self.assertIn("apiDocumentation", summ["_api"])

    # -- full detail is never truncated ----------------------------------
    def test_json_passthrough_is_lossless(self):
        doc = self.client().subject("GRGRMAT01")
        self.assertEqual(doc, load("subject_GRGRMAT01.json"))

    def test_html_to_text_readable(self):
        text = html_to_text({"text": "<h3>Centralt innehåll</h3><ul><li>Proportionalitet</li></ul>"})
        self.assertIn("Centralt", text)
        self.assertIn("Proportionalitet", text)
        self.assertNotIn("<", text)

    # -- errors -----------------------------------------------------------
    def test_unknown_code_raises_helpful_404(self):
        with self.assertRaises(SkolverketError) as ctx:
            self.client().subject("NOPE99")
        self.assertIn("404", str(ctx.exception))
        self.assertTrue(ctx.exception.hint, "404 must suggest how to find valid codes")

    def test_network_error_message_names_url(self):
        def boom(req, timeout=None):
            raise urllib.error.URLError("boom")

        skolverket.urllib.request.urlopen = boom
        with self.assertRaises(SkolverketError) as ctx:
            self.client().subject("MAT")
        self.assertIn("api.skolverket.se", str(ctx.exception))

    # -- CLI ---------------------------------------------------------------
    def run_cli(self, *args):
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = skolverket.run(["--no-cache", *args])
        return code, buf_out.getvalue(), buf_err.getvalue()

    def test_cli_subject_summary_json(self):
        code, out, _ = self.run_cli("--format", "summary", "subject", "MATE")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["reform"], "GY25")
        self.assertEqual(payload["courses"][0]["code"], "MATE1A00X")

    def test_cli_query_filters_and_missing_query_errors(self):
        code, out, _ = self.run_cli("--format", "summary", "subjects", "--query", "kemi")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["totalElements"], 1)
        code, _, err = self.run_cli("subjects", "--query", "xyzzy")
        self.assertEqual(code, 3)
        self.assertIn("No subjects matching", json.loads(err)["error"])

    def test_cli_text_format_readable(self):
        code, out, _ = self.run_cli("--format", "text", "subject", "GRGRMAT01")
        self.assertEqual(code, 0)
        self.assertIn("Matematik", out)
        self.assertNotIn("<li>", out)


if __name__ == "__main__":
    unittest.main()
