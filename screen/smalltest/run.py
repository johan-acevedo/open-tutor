"""Small live-model test for Smart Screen pages.

Calls two models on the Go OpenAI-compatible endpoint for each case in
requests.json (page, then patch), saves bodies + raw replies, renders each
page with its patch via screenkit, and writes results.json + summary.md.

Run (key comes from the env wrapper, never printed):
  OPEN_TUTOR_ENV=~/.config/open-tutor-screen-dev/env server/bin/with-env \
    uv run --project server python screen/smalltest/run.py

Sequential calls only. One retry at most per call; errors are recorded and
the run continues.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import prompt as prompt_mod
import screenkit
from open_tutor.config import USER_AGENT

BASE_URL = "https://opencode.ai/inference/go/openai/v1"
OUT = pathlib.Path(os.environ.get("SMALLTEST_OUT", ROOT / "smalltest" / "out"))

MODELS = [
    {
        "folder": "muse",
        "session": "smalltest-muse",
        "api": "responses",
        "model": "muse-spark-1.3-contributor",
        "reasoning_effort": "minimal",
    },
    {
        "folder": "deepseek",
        "session": "smalltest-deepseek",
        "api": "chat",
        "model": "deepseek-v4.1-flash",
        "reasoning_effort": "low",
    },
]

FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n")
FENCE_CLOSE = re.compile(r"\n\s*```\s*$")


def strip_fences(text: str) -> str:
    """Remove one accidental ``` code fence wrapper, if present."""
    t = text.strip()
    if t.startswith("```"):
        t = FENCE_OPEN.sub("", t, count=1)
        t = FENCE_CLOSE.sub("", t, count=1)
    return t.strip() + ("\n" if t else "")


def usage_dict(u) -> dict:
    if u is None:
        return {}
    d = {
        "input_tokens": getattr(u, "input_tokens", None),
        "output_tokens": getattr(u, "output_tokens", None),
        "total_tokens": getattr(u, "total_tokens", None),
    }
    det = getattr(u, "input_tokens_details", None)
    if det is not None:
        d["cached_tokens"] = getattr(det, "cached_tokens", None)
    out = getattr(u, "output_tokens_details", None)
    if out is not None:
        d["reasoning_tokens"] = getattr(out, "reasoning_tokens", None)
    return {k: v for k, v in d.items() if v is not None}


def call_responses(client, model: str, system: str, user_text: str, effort: str) -> dict:
    """One Responses API streaming call. Returns timings/text/usage."""
    from openai.types import Reasoning

    t0 = time.monotonic()
    first_text = None
    text_parts: list[str] = []
    usage = None
    stream = client.responses.create(
        model=model,
        instructions=system,
        input=user_text,
        reasoning=Reasoning(effort=effort),
        store=False,
        stream=True,
    )
    with stream as s:
        for event in s:
            etype = getattr(event, "type", "")
            if etype in ("response.output_text.delta",) and first_text is None:
                delta = getattr(event, "delta", "")
                if delta:
                    first_text = time.monotonic() - t0
            if etype == "response.output_text.delta":
                text_parts.append(getattr(event, "delta", ""))
            elif etype == "response.completed":
                usage = usage_dict(getattr(getattr(event, "response", None), "usage", None))
    total = time.monotonic() - t0
    text = "".join(text_parts)
    return {
        "first_text_s": round(first_text, 2) if first_text is not None else None,
        "total_s": round(total, 2),
        "chars": len(text),
        "usage": usage or {},
        "text": text,
    }


def call_chat(client, model: str, system: str, user_text: str, effort: str) -> dict:
    """One Chat Completions streaming call. Returns timings/text/usage."""
    t0 = time.monotonic()
    first_text = None
    text_parts: list[str] = []
    usage = None
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
        stream=True,
        stream_options={"include_usage": True},
        reasoning_effort=effort,
    )
    with stream as s:
        for chunk in s:
            choices = getattr(chunk, "choices", None) or []
            delta = getattr(choices[0], "delta", None) if choices else None
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                if first_text is None:
                    first_text = time.monotonic() - t0
                text_parts.append(content)
            if getattr(chunk, "usage", None) is not None:
                usage = usage_dict(chunk.usage)
    total = time.monotonic() - t0
    text = "".join(text_parts)
    return {
        "first_text_s": round(first_text, 2) if first_text is not None else None,
        "total_s": round(total, 2),
        "chars": len(text),
        "usage": usage or {},
        "text": text,
    }


def do_call(spec: dict, client, system: str, user_text: str) -> dict:
    """Call once, retry once at most. Never raises: errors are returned."""
    last_error = None
    for attempt in (1, 2):
        try:
            if spec["api"] == "responses":
                out = call_responses(client, spec["model"], system, user_text, spec["reasoning_effort"])
            else:
                out = call_chat(client, spec["model"], system, user_text, spec["reasoning_effort"])
            out["error"] = None
            out["attempts"] = attempt
            # Fallback model id for DeepSeek: the Go endpoint may want the
            # pi-style prefixed id. Only used when the exact id 404s.
            return out
        except Exception as e:  # noqa: BLE001 - recorded, run continues
            last_error = f"{type(e).__name__}: {e}"[:500]
            if attempt == 1 and spec["folder"] == "deepseek" and "model" in last_error.lower():
                spec["model"] = "opencode-go/deepseek-v4.1-flash"
                continue
            if attempt == 1:
                time.sleep(2)
    return {
        "first_text_s": None,
        "total_s": None,
        "chars": 0,
        "usage": {},
        "text": "",
        "error": last_error,
        "attempts": 2,
    }


def main() -> int:
    from openai import OpenAI

    api_key = os.environ.get("OPENCODE_GO_API_KEY", "")
    if not api_key:
        print("OPENCODE_GO_API_KEY is empty: run through server/bin/with-env", file=sys.stderr)
        return 2

    cases = json.loads((ROOT / "smalltest" / "requests.json").read_text())
    system = prompt_mod.system_prompt()
    print(f"system prompt: {len(system)} chars", flush=True)

    results: dict = {"models": {}}
    for spec in MODELS:
        model_dir = OUT / spec["folder"]
        shots_dir = model_dir / "shots"
        model_dir.mkdir(parents=True, exist_ok=True)
        shots_dir.mkdir(parents=True, exist_ok=True)
        client = OpenAI(
            api_key=api_key,
            base_url=BASE_URL,
            default_headers={"User-Agent": USER_AGENT, "x-opencode-session": spec["session"]},
            timeout=300.0,
            max_retries=0,
        )
        model_res: dict = {
            "model_id": spec["model"],
            "api": spec["api"],
            "session": spec["session"],
            "cases": {},
        }
        render_reports: dict = {}
        for case in cases:
            cid = case["id"]
            print(f"[{spec['folder']}] {cid}: page ...", flush=True)
            page = do_call(spec, client, system, prompt_mod.page_request(case["request"], case.get("child", "")))
            page_body = strip_fences(page["text"]) if not page["error"] else ""
            (model_dir / f"{cid}.raw.txt").write_text(page["text"])
            (model_dir / f"{cid}.html").write_text(page_body)

            patch = {"first_text_s": None, "total_s": None, "chars": 0, "usage": {},
                     "text": "", "error": "skipped: page call failed", "attempts": 0}
            patch_body = ""
            if not page["error"] and page_body:
                print(f"[{spec['folder']}] {cid}: patch ...", flush=True)
                patch = do_call(spec, client, system, prompt_mod.patch_request(case["patch"], page_body))
                patch_body = strip_fences(patch["text"]) if not patch["error"] else ""
            (model_dir / f"{cid}.patch.raw.txt").write_text(patch["text"])
            (model_dir / f"{cid}.patch.html").write_text(patch_body)

            model_res["cases"][cid] = {
                "page": {k: v for k, v in page.items() if k != "text"},
                "patch": {k: v for k, v in patch.items() if k != "text"},
            }
            model_res["model_id"] = spec["model"]  # may have changed via fallback
            print(f"[{spec['folder']}] {cid}: page total={page['total_s']}s first={page['first_text_s']}s "
                  f"chars={page['chars']} err={page['error']} | "
                  f"patch total={patch['total_s']}s first={patch['first_text_s']}s "
                  f"chars={patch['chars']} err={patch['error']}", flush=True)

        # Render all pages of this model with one shared browser.
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    for case in cases:
                        cid = case["id"]
                        body = (model_dir / f"{cid}.html").read_text()
                        patch_html = (model_dir / f"{cid}.patch.html").read_text()
                        if not body.strip():
                            render_reports[cid] = {"error": "empty page body, not rendered"}
                            continue
                        try:
                            rep = screenkit.render(
                                body, shots_dir, cid,
                                patch=patch_html if patch_html.strip() else None,
                                browser=browser)
                            render_reports[cid] = rep
                        except Exception as e:  # noqa: BLE001
                            render_reports[cid] = {"error": f"{type(e).__name__}: {e}"[:500]}
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001 - playwright missing etc.
            print(f"[{spec['folder']}] render setup failed: {e}", flush=True)

        for cid, rep in render_reports.items():
            entry = model_res["cases"][cid]
            if "error" in rep and "sizes" not in rep:
                entry["render_error"] = rep["error"]
                continue
            for size_key, sentry in rep.get("sizes", {}).items():
                entry.setdefault("render", {})[size_key] = {
                    "ready_ms": sentry.get("ready_ms"),
                    "fontPx": sentry.get("fontPx"),
                    "issues": sentry.get("issues"),
                    "patch_issues": sentry.get("patch_issues"),
                    "fontPx_after": sentry.get("fontPx_after"),
                }
        results["models"][spec["folder"]] = model_res

    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    (OUT / "summary.md").write_text(make_summary(results))
    print("wrote results.json and summary.md", flush=True)
    return 0


def make_summary(results: dict) -> str:
    L: list[str] = []
    L.append("# smalltest summary")
    L.append("")
    L.append("| model | case | page first (s) | page total (s) | page chars | "
             "patch first (s) | patch total (s) | patch chars | errors |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for folder, m in results["models"].items():
        for cid, c in m["cases"].items():
            p, q = c["page"], c["patch"]
            errs = "; ".join(e for e in [p.get("error"), q.get("error")] if e)
            L.append(f"| {folder} | {cid} | {p.get('first_text_s')} | {p.get('total_s')} | "
                     f"{p.get('chars')} | {q.get('first_text_s')} | {q.get('total_s')} | "
                     f"{q.get('chars')} | {errs or '-'} |")
    L.append("")
    L.append("## usage")
    L.append("")
    for folder, m in results["models"].items():
        L.append(f"### {folder} ({m.get('model_id')})")
        L.append("")
        for cid, c in m["cases"].items():
            L.append(f"- {cid} page: `{json.dumps(c['page'].get('usage', {}), ensure_ascii=False)}` "
                     f"patch: `{json.dumps(c['patch'].get('usage', {}), ensure_ascii=False)}`")
        L.append("")
    L.append("## render lint (screenkit issues)")
    L.append("")
    for folder, m in results["models"].items():
        L.append(f"### {folder}")
        L.append("")
        for cid, c in m["cases"].items():
            if "render_error" in c:
                L.append(f"- {cid}: render error: {c['render_error']}")
                continue
            for size_key, r in (c.get("render") or {}).items():
                L.append(f"- {cid} {size_key}: ready_ms={r.get('ready_ms')} fontPx={r.get('fontPx')} "
                         f"issues={json.dumps(r.get('issues'), ensure_ascii=False)} "
                         f"patch_issues={json.dumps(r.get('patch_issues'), ensure_ascii=False)}")
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
