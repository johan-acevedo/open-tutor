"""The Screen agent on the server: the Smart Screen live slice.

One Screen per session, owned by the worker next to the Tutor. It follows the
lesson (conversation turns, shared homework, the child's answers from pages,
what is visible) and works in the background: ``ask()`` returns a job id at
once, the job runs as a background task, and the result is handed to the tutor
through callbacks the worker wires up (``on_page``, ``on_patch``,
``on_failure``).

The model call and the renderer are injectable so tests need no network or
browser. The real paths import the static prompt and the render helpers from
``screen/tools/`` rather than copying them; the repo root is added to
``sys.path`` so this works when the worker runs from ``server/``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

log = logging.getLogger("open-tutor")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from screen.tools import prompt as screen_prompt  # noqa: E402
from screen.tools import screenkit as screenkit  # noqa: E402
from screen.tools.page_images import PageImages  # noqa: E402

SCREEN_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
JOB_TIMEOUT_S = 20.0
PAGE_TARGET_S = 12.0
OPTIONAL_STEP_LIMIT_S = 6.0
# Defaults: Muse Spark on Responses with minimal reasoning. DeepSeek models use
# Chat Completions with low reasoning. SCREEN_MODEL / SCREEN_REASONING override;
# the model itself is never changed by the timing work (see docs/smart-screen.md).
MAX_TURNS = 40  # conversation turns kept per request; sessions run long
MAX_HOMEWORK_IMAGES = 4
# Optional repair work (the look pass, the one lint retry) may not eat the
# delivery: a step only starts while a final render still fits the job limit.
FINAL_RENDER_RESERVE_S = 3.0
DELIVERY_RESERVE_S = 0.2
MIN_OPTIONAL_STEP_S = 2.0
IMAGE_BUDGET_S = 6.0
# The shell's `dense` minimum is 16 px below 600 px wide (screen/shell/shell.js).
NARROW_PANE_WIDTH = 600
NARROW_PANE_HEIGHT = 640


def session_pages_dir(room: str, debug_dir: Path | str | None = None) -> Path:
    """Where a session's pages live: ``pages/`` under the session log folder."""
    from .debug_log import default_dir_with_env, sanitize_id

    base = Path(debug_dir) if debug_dir else default_dir_with_env(os.environ) / sanitize_id(room)
    pages = base / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
        os.chmod(pages, 0o700)
    except OSError:
        pass
    return pages


# ---- answer classification -------------------------------------------------

_FENCE_OPEN = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*\n")
_FENCE_CLOSE = re.compile(r"\n\s*```\s*$")


def strip_fences(text: str) -> str:
    """Remove one accidental ``` code fence wrapper, if present."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = _FENCE_OPEN.sub("", t, count=1)
        t = _FENCE_CLOSE.sub("", t, count=1)
    return t.strip()


def classify_answer(text: str) -> str:
    """A screen model answer is either ``"patch"`` (``<ot-patch>`` elements
    changing the visible page) or ``"page"`` (a new page body)."""
    return "patch" if "<ot-patch" in (text or "") else "page"


def page_title(body: str, fallback: str) -> str:
    """The page title travels with the ``page`` item; take it from the first h1."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", body or "", re.DOTALL | re.IGNORECASE)
    if match:
        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if title:
            return title[:120]
    return fallback


# ---- pane -------------------------------------------------------------------

def pane_is_narrow(width: int, height: int) -> bool:
    """A phone or a small split window: readable without scrolling is the rule."""
    return int(width) <= NARROW_PANE_WIDTH or int(height) <= NARROW_PANE_HEIGHT


def pane_context(width: int, height: int) -> str:
    """The pane facts the page writer needs; narrow panes get the layout rule."""
    if pane_is_narrow(width, height):
        return (f"Pane: {width}×{height} px, narrow. Write one reading column, a short title "
                f"(two to four words) and one teaching step or one visual. No second column, "
                f"no side panel, nothing that needs scrolling.")
    return f"Pane: {width}×{height} px. Fill it without scrolling; scale the content to the pane."


# ---- lint -------------------------------------------------------------------

# Issues arrive as {"kind", "msg", "where"} dicts from the shell. A retry only
# earns its time on problems a page body can fix; slow loading and image
# credits are advisory and stay in the log instead.
ADVISORY_LINT_KINDS = frozenset({"slow", "load", "image"})
_ADVISORY_IMAGE_WORDS = ("credit", "källa", "search failed", "failed to load")


def issue_kind(issue: Any) -> str:
    """The shell kind of one issue; a plain string may carry it as a prefix."""
    if isinstance(issue, dict):
        return str(issue.get("kind") or "").strip().lower()
    match = re.match(r"\s*([A-Za-z_-]+)\s*:", str(issue or ""))
    return match.group(1).lower() if match else ""


def issue_text(issue: Any) -> str:
    """One issue as the model and the log see it: kind, message and element."""
    if isinstance(issue, dict):
        kind = issue_kind(issue)
        msg = str(issue.get("msg") or issue.get("message") or "").strip()
        where = str(issue.get("where") or "").strip()
        text = f"{kind}: {msg}" if kind and msg else (kind or msg)
        return f"{text} ({where})" if where else text
    return str(issue or "").strip()


def is_actionable(issue: Any) -> bool:
    """True when a rewritten page body can fix it in one bounded step."""
    kind = issue_kind(issue)
    if kind not in ADVISORY_LINT_KINDS:
        return True
    if kind == "image":
        text = issue_text(issue).lower()
        return not any(word in text for word in _ADVISORY_IMAGE_WORDS)
    return False


def actionable_issues(issues: Iterable[Any] | None) -> list[str]:
    """The exact lint lines worth one correction, in the shell's order."""
    return [issue_text(issue) for issue in (issues or [])
            if issue_text(issue) and is_actionable(issue)]


# ---- results ----------------------------------------------------------------

@dataclass
class PageResult:
    job_id: str
    page_id: str
    title: str
    body: str
    png: bytes
    issues: list = field(default_factory=list)
    model_s: float = 0.0
    render_s: float = 0.0
    look_s: float = 0.0
    retry_s: float = 0.0
    total_s: float = 0.0
    directory: Path | None = None
    residual_issues: list[str] = field(default_factory=list)


@dataclass
class PatchResult:
    job_id: str
    page_id: str
    patch: str
    png: bytes
    issues: list = field(default_factory=list)
    model_s: float = 0.0
    render_s: float = 0.0
    total_s: float = 0.0
    directory: Path | None = None


# Injectable seams. The model call gets the static system prompt, the lesson
# user text, homework image data URLs and (look pass only) the render
# screenshot, and returns the model's raw text. The renderer gets the page
# body (plus a patch, when the model answered one) and the child's pane size,
# and returns the screenshot bytes plus the shell's issues.
ModelCall = Callable[[str, str, list[str], bytes | None], Any]
RenderPage = Callable[[str, str | None, int, int], Any]


def _screen_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


class Screen:
    """Follows one session's lesson and renders screen pages in the background."""

    def __init__(
        self,
        learner: dict[str, Any] | None,
        pages_dir: Path | str,
        *,
        session_id: str = "screen",
        model_call: ModelCall | None = None,
        render_page: RenderPage | None = None,
        get_pane_size: Callable[[], tuple[int, int]] | None = None,
        timeout: float = JOB_TIMEOUT_S,
    ) -> None:
        self.learner = learner or {}
        self.pages_dir = Path(pages_dir)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self._model_call = model_call or self._default_model_call
        self._render_page = render_page or self._default_render_page
        self._get_pane_size = get_pane_size or (lambda: (1366, 768))
        self.timeout = timeout
        self.turns: list[tuple[str, str]] = []  # ("child"|"tutor", text)
        self.homework: list[tuple[str, list[str]]] = []  # (description, image data URLs)
        self.answers: list[dict[str, str]] = []
        self.pages: dict[str, PageResult] = {}
        self.visible_id: str | None = None
        self.visible_patches: list[str] = []
        self.on_page: Callable[[PageResult], Any] | None = None
        self.on_patch: Callable[[PatchResult], Any] | None = None
        self.on_failure: Callable[[str], Any] | None = None
        self._job_counter = 0
        self._page_counter = 0
        self._pending: tuple[str, str] | None = None
        self._runner: asyncio.Task | None = None
        self._pw = None
        self._browser = None
        self._system: str | None = None  # static prefix, computed once so every
        # call sends byte-identical instructions (provider prompt caching).

    # ---- lesson ----------------------------------------------------------

    def add_turn(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text or role not in ("child", "tutor"):
            return
        self.turns.append((role, text[:2000]))

    def add_homework(self, description: str, image_urls: list[str] | None = None) -> None:
        self.homework.append(((description or "")[:500], list(image_urls or [])[:8]))

    def record_answer(self, page: str, part: str, value: str, kind: str = "") -> None:
        self.answers.append({"page": page or "", "part": part or "",
                             "value": (value or "")[:500], "kind": kind or ""})

    def page(self, page_id: str) -> PageResult | None:
        return self.pages.get((page_id or "").strip())

    def set_pane_source(self, get_pane_size: Callable[[], tuple[int, int]]) -> None:
        """Render at the live pane size (the worker keeps it current)."""
        self._get_pane_size = get_pane_size

    def mark_visible(self, page_id: str) -> None:
        if page_id in self.pages and page_id != self.visible_id:
            self.visible_id = page_id
            self.visible_patches = []

    # ---- jobs ------------------------------------------------------------

    def ask(self, text: str) -> str:
        """Queue one screen job; returns the job id at once. Latest wins: an
        ask waiting behind a running job is replaced by a newer one."""
        from .debug_log import record_active

        self._job_counter += 1
        job_id = f"s{self._job_counter}"
        record_active("screen_ask", {"job": job_id, "ask": (text or "")[:300]})
        self._pending = (job_id, (text or "").strip())
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._pump())
        return job_id

    async def wait_idle(self) -> None:
        while (self._runner is not None and not self._runner.done()) or self._pending is not None:
            try:
                if self._runner is not None:
                    await self._runner
                else:
                    await asyncio.sleep(0.01)
            except Exception:
                pass

    async def aclose(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def _pump(self) -> None:
        while self._pending is not None:
            job_id, text = self._pending
            self._pending = None
            try:
                await asyncio.wait_for(self._run_job(job_id, text), timeout=self.timeout)
            except asyncio.TimeoutError:
                log.warning("screen job %s timed out", job_id)
                await self._fail(job_id, "The screen took too long. Explain in words instead, briefly.")
            except Exception as error:  # noqa: BLE001 - told to the tutor, run continues
                log.warning("screen job %s failed: %s", job_id, error)
                await self._fail(job_id, "The screen could not prepare that. Explain in words instead, briefly.")

    async def _fail(self, job_id: str, message: str) -> None:
        from .debug_log import record_active

        record_active("screen_failed", {"job": job_id, "message": message[:200]})
        if self.on_failure is not None:
            result = self.on_failure(message)
            if inspect.isawaitable(result):
                await result

    def system_prompt(self) -> str:
        """The static prefix, computed once per session and reused verbatim."""
        if self._system is None:
            self._system = screen_prompt.system_prompt()
        return self._system

    async def warmup(self) -> None:
        """Start the headless browser now (at session start) so the first job
        does not pay for the launch. Safe to call more than once."""
        try:
            from playwright.async_api import async_playwright

            if self._pw is None:
                self._pw = await async_playwright().start()
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._pw.chromium.launch()
        except Exception as error:  # noqa: BLE001 - first job will retry
            log.warning("screen warmup failed: %s", error)

    def _learner_line(self) -> str:
        name = str(self.learner.get("name") or "").strip()[:40] or "eleven"
        grade = self.learner.get("grade")
        if isinstance(grade, int) and 1 <= grade <= 12:
            level = f"åk {grade}" if grade <= 9 else f"gymnasiet år {grade - 9}"
            return f"Child: {name}, {level}."
        return f"Child: {name}."

    def _build_user_text(self, ask: str) -> str:
        width, height = self._pane_size()
        parts = [self._learner_line(), pane_context(width, height)]
        for i, (description, _) in enumerate(self.homework, 1):
            parts.append(f"Shared homework {i}: {description}")
        if self.turns:
            parts.append("Conversation so far:")
            for role, text in self.turns[-MAX_TURNS:]:
                who = "Child" if role == "child" else "Tutor"
                parts.append(f"{who}: {text}")
        else:
            parts.append("No conversation yet.")
        if self.visible_id is not None and self.visible_id in self.pages:
            visible = self.pages[self.visible_id]
            parts.append(f"The page on screen now (id {visible.page_id}, title {visible.title}):\n\n{visible.body}")
            for patch in self.visible_patches:
                parts.append(f"A change already applied to it:\n\n{patch}")
            parts.append(
                f"Tutor: {ask}\n\nAnswer with <ot-patch> elements if a small change "
                f"to the page on screen is enough, else a new page body.")
        else:
            parts.append("No page is on screen yet.")
            parts.append(f"Tutor: {ask}\n\nAnswer with a new page body.")
        return "\n\n".join(parts)

    def _homework_images(self) -> list[str]:
        urls: list[str] = []
        for _, image_urls in self.homework:
            urls.extend(image_urls)
        return urls[:MAX_HOMEWORK_IMAGES]

    async def _call_model(self, system: str, user: str,
                          look_png: bytes | None = None) -> tuple[str, float]:
        t0 = time.monotonic()
        if inspect.iscoroutinefunction(self._model_call):
            result = await self._model_call(system, user, self._homework_images(), look_png)
        else:
            # Blocking (the real OpenAI client): off the event loop.
            result = await asyncio.to_thread(self._model_call, system, user,
                                             self._homework_images(), look_png)
        return str(result), time.monotonic() - t0

    async def _render(self, body: str, patch: str | None) -> tuple[bytes, list, float]:
        width, height = self._pane_size()
        t0 = time.monotonic()
        result = self._render_page(body, patch, width, height)
        if inspect.isawaitable(result):
            result = await result
        png, issues = result
        return bytes(png), list(issues or []), time.monotonic() - t0

    def _pane_size(self) -> tuple[int, int]:
        try:
            w, h = self._get_pane_size()
            return max(320, min(int(w), 3840)), max(320, min(int(h), 3840))
        except Exception:
            return 1366, 768

    def _save(self, job_id: str, ask: str, files: dict[str, Any], meta: dict[str, Any]) -> Path:
        job_dir = self.pages_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "ask.txt").write_text(ask, encoding="utf-8")
        for name, content in files.items():
            path = job_dir / name
            if isinstance(content, (bytes, bytearray)):
                path.write_bytes(bytes(content))
            else:
                path.write_text(str(content), encoding="utf-8")
        (job_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return job_dir

    def model_spec(self) -> dict[str, str]:
        """Which screen model and reasoning level this session uses."""
        model = _screen_env("SCREEN_MODEL", "muse-spark-1.3-contributor")
        gemini = model.lower().startswith("gemini-")
        deepseek = "deepseek" in model.lower()
        api = _screen_env("SCREEN_API", "") or ("chat" if deepseek or gemini else "responses")
        effort = _screen_env("SCREEN_REASONING", "") or ("low" if api == "chat" else "minimal")
        thinking = _screen_env("SCREEN_THINKING", "")
        if gemini and (api != "chat" or effort not in {"low", "medium", "high"}):
            raise ValueError("Gemini pages require SCREEN_API=chat and SCREEN_REASONING=low, medium or high")
        if thinking and (not deepseek or api != "chat" or thinking not in {"enabled", "disabled"}):
            raise ValueError("SCREEN_THINKING=enabled|disabled requires a DeepSeek chat model")
        spec = {"model": model, "api": api, "reasoning": effort}
        if thinking:
            spec["thinking"] = thinking
        return spec

    async def _run_job(self, job_id: str, ask: str) -> None:
        from .debug_log import record_active

        t0 = time.monotonic()
        if not ask:
            await self._fail(job_id, "The screen got an empty ask. Explain in words instead, briefly.")
            return
        system = self.system_prompt()
        user = self._build_user_text(ask)
        generation_time = self.timeout - min(2.0, self.timeout * 0.2)
        answer, model_s = await asyncio.wait_for(self._call_model(system, user), timeout=generation_time)
        answer = strip_fences(answer)
        if not answer:
            await self._fail(job_id, "The screen answered empty. Explain in words instead, briefly.")
            return
        kind = classify_answer(answer)
        if kind == "patch":
            await self._run_patch(job_id, ask, answer, model_s, t0)
        else:
            await self._run_page(job_id, ask, answer, model_s, t0)

    async def _run_patch(self, job_id: str, ask: str, patch: str,
                         model_s: float, t0: float) -> None:
        from .debug_log import record_active

        if self.visible_id is None or self.visible_id not in self.pages:
            await self._fail(job_id, "The screen answered a change but no page is on screen. "
                                     "Explain in words instead, briefly.")
            return
        visible = self.pages[self.visible_id]
        images = self._image_job(ask, t0)
        patch = await images.prepare(patch)
        png, issues, render_s = await self._render(visible.body, patch)
        errors = [issue_text(i) for i in issues
                  if issue_kind(i) == "patch" or str(i).startswith("patch failed:")]
        total_s = time.monotonic() - t0
        spec = self.model_spec()
        w, h = self._pane_size()
        job_dir = self._save(job_id, ask,
                             {"patch.html": patch, "patched.png": png, "images.json": json.dumps(images.events, ensure_ascii=False)},
                             {"job": job_id, "kind": "patch", "page": visible.page_id,
                              **spec,
                              "pane": [w, h],
                              "model_s": round(model_s, 2), "render_s": round(render_s, 2),
                              "total_s": round(total_s, 2), "issues": issues,
                              "delivered": not errors,
                              "image_s": round(images.seconds, 2), "image_reviews": images.events})
        record_active("screen_patch", {"job": job_id, "page": visible.page_id,
                                       "total_s": round(total_s, 2), "issues": issues,
                                       "delivered": not errors})
        if errors:
            await self._fail(job_id, "The screen change was not applied: " + "; ".join(errors)[:400]
                             + ". Ask for a corrected change or a new page; explain in words meanwhile.")
            return
        self.visible_patches.append(patch)
        result = PatchResult(job_id=job_id, page_id=visible.page_id, patch=patch,
                             png=png, issues=issues, model_s=model_s,
                             render_s=render_s, total_s=total_s, directory=job_dir)
        if self.on_patch is not None:
            outcome = self.on_patch(result)
            if inspect.isawaitable(outcome):
                await outcome

    async def _run_page(self, job_id: str, ask: str, body: str,
                        model_s: float, t0: float) -> None:
        from .debug_log import record_active

        self._page_counter += 1
        page_id = f"p{self._page_counter}"
        width, height = self._pane_size()
        images = self._image_job(ask, t0)
        body = await images.prepare(body)
        png, issues, render_s = await self._render(body, None)
        reserve_s = max(render_s, FINAL_RENDER_RESERVE_S)
        step_s = MIN_OPTIONAL_STEP_S
        look_s = retry_s = 0.0
        repair: dict[str, Any] = {"look": False, "look_fix": False, "retry": False,
                                  "retry_applied": False, "notes": []}

        # Spend the soft target only on optional inspection. Known lint goes
        # straight to one correction instead of paying for a look first.
        look_mode = _screen_env("SCREEN_LOOK", "1")
        look_target = self.timeout if look_mode == "always" else min(self.timeout, PAGE_TARGET_S)
        if look_mode != "0" and not actionable_issues(issues):
            if look_target - (time.monotonic() - t0) >= step_s + reserve_s:
                repair["look"] = True
                fixed, look_s, why = await self._bounded(
                    t0, reserve_s, self._look_once(ask, body, png, issues, width, height), target_s=look_target)
                if why:
                    repair["notes"].append(f"look pass {why}")
                elif fixed and fixed != body:
                    if self._time_left(t0) < reserve_s:
                        repair["notes"].append("look fix not rendered: no time left")
                    else:
                        fixed = await images.prepare(fixed)
                        rendered, why = await self._render_optional(fixed, t0)
                        if rendered is None:
                            repair["notes"].append(f"look fix dropped: {why}")
                        else:
                            body, png, issues = fixed, rendered[0], rendered[1]
                            render_s += rendered[2]
                            reserve_s = max(reserve_s, rendered[2])
                            repair["look_fix"] = True
            else:
                repair["notes"].append("look pass skipped: page target budget")
        elif look_mode != "0" and actionable_issues(issues):
            repair["notes"].append("look pass skipped: correct lint directly")

        # One corrective retry when actionable lint is still there: the page
        # source, the ask, the pane and the exact lint text. Advisory issues
        # (slow loading, image credits) never buy a retry.
        leftover = actionable_issues(issues)
        if leftover and not repair["look"] and _screen_env("SCREEN_LINT_RETRY", "1") != "0":
            if self._time_left(t0) >= step_s + reserve_s:
                repair["retry"] = True
                corrected, retry_s, why = await self._bounded(
                    t0, reserve_s, self._retry_with_lint(ask, body, leftover, width, height))
                if why:
                    repair["notes"].append(f"lint retry {why}")
                elif corrected and corrected != body:
                    corrected = await images.prepare(corrected)
                    rendered, why = await self._render_optional(corrected, t0)
                    if rendered is None:
                        repair["notes"].append(f"lint retry dropped: {why}")
                    elif len(actionable_issues(rendered[1])) > len(leftover):
                        repair["notes"].append("lint retry made lint worse; kept the first page")
                    else:
                        body, png, issues = corrected, rendered[0], rendered[1]
                        render_s += rendered[2]
                        reserve_s = max(reserve_s, rendered[2])
                        repair["retry_applied"] = True
            else:
                repair["notes"].append("lint retry skipped: no time left")

        # Whatever is still reported ships with the page, in the log and in
        # meta.json: a usable page is never dropped for optional repair work.
        residual = actionable_issues(issues)
        if residual:
            log.warning("screen page %s delivered with residual lint: %s",
                        page_id, "; ".join(residual))
        if not repair["look"]:
            log.info("screen page %s delivered without look: %s", page_id,
                     "; ".join(repair["notes"]) or "disabled")
        total_s = time.monotonic() - t0
        spec = self.model_spec()
        job_dir = self._save(job_id, ask,
                             {"page.html": body, "shot.png": png, "images.json": json.dumps(images.events, ensure_ascii=False)},
                             {"job": job_id, "kind": "page", "page": page_id,
                              "title": page_title(body, page_id),
                              **spec,
                              "pane": [width, height],
                              "model_s": round(model_s, 2), "render_s": round(render_s, 2),
                              "look_s": round(look_s, 2), "retry_s": round(retry_s, 2),
                              "total_s": round(total_s, 2), "issues": issues,
                              "residual_lint": residual, "repair": repair,
                              "image_s": round(images.seconds, 2), "image_reviews": images.events})
        if images.events:
            record_active("screen_images", {"job": job_id, "seconds": round(images.seconds, 2),
                                            "reviews": images.events})
        record_active("screen_page", {"job": job_id, "page": page_id,
                                      "total_s": round(total_s, 2), "issues": issues,
                                      "residual_lint": residual,
                                      "look": repair["look"], "repair_notes": repair["notes"],
                                      "retry": repair["retry"],
                                      "retry_applied": repair["retry_applied"]})
        result = PageResult(job_id=job_id, page_id=page_id,
                            title=page_title(body, page_id), body=body, png=png,
                            issues=issues, model_s=model_s, render_s=render_s,
                            look_s=look_s, retry_s=retry_s, total_s=total_s,
                            directory=job_dir, residual_issues=residual)
        self.pages[page_id] = result
        if self.on_page is not None:
            outcome = self.on_page(result)
            if inspect.isawaitable(outcome):
                await outcome

    def _image_job(self, ask: str, t0: float) -> PageImages:
        async def review(user: str, image: bytes | None) -> str:
            text, _ = await self._call_model(
                "Choose an educational image for a Swedish school child. Inspect the actual picture with the lesson context. "
                "Return only the requested JSON decision, reason and a text/HTML alternative if rejected.", user, image)
            return text

        deadline = min(time.monotonic() + IMAGE_BUDGET_S,
                       t0 + min(self.timeout, PAGE_TARGET_S) - FINAL_RENDER_RESERVE_S - DELIVERY_RESERVE_S)
        return PageImages(self._build_user_text(ask), review, deadline)

    def _time_left(self, t0: float) -> float:
        """Seconds until the job limit; optional work is spent from this."""
        return self.timeout - (time.monotonic() - t0)

    async def _bounded(self, t0: float, reserve_s: float,
                       call: Awaitable[Any], *, target_s: float | None = None) -> tuple[Any, float, str]:
        """Run one optional model step inside the job budget; it never raises.
        Returns (result, seconds, why-not), with why-not empty on success."""
        started = time.monotonic()
        try:
            remaining = self._time_left(t0) - reserve_s
            if target_s is not None:
                remaining = min(remaining, target_s - (started - t0) - reserve_s)
            result = await asyncio.wait_for(call, timeout=max(0.001, min(OPTIONAL_STEP_LIMIT_S, remaining)))
        except asyncio.TimeoutError:
            return None, time.monotonic() - started, "timed out"
        except Exception as error:  # noqa: BLE001 - the page still ships
            return None, time.monotonic() - started, f"failed: {type(error).__name__}"
        return result, time.monotonic() - started, ""

    async def _render_optional(self, body: str, t0: float) -> tuple[tuple[bytes, list, float] | None, str]:
        """Re-render a repair; a failure keeps the page already in hand."""
        try:
            remaining = self._time_left(t0) - DELIVERY_RESERVE_S
            if remaining <= 0:
                return None, "no time left for render"
            png, issues, render_s = await asyncio.wait_for(self._render(body, None), timeout=remaining)
        except asyncio.TimeoutError:
            return None, "render timed out"
        except Exception as error:  # noqa: BLE001 - a usable page is not dropped
            return None, f"render failed: {type(error).__name__}"
        return (png, issues, render_s), ""

    async def _look_once(self, ask: str, body: str, png: bytes, issues: list,
                         width: int, height: int) -> str | None:
        """Show the model its own render and source; it answers OK or a body."""
        from .debug_log import record_active

        reported = "\n".join(f"- {issue_text(issue)}" for issue in issues) or "- none"
        user = (
            f"The tutor's ask was: {ask}\n\n"
            f"{pane_context(width, height)}\n\n"
            f"Your page body (source):\n\n{body}\n\n"
            f"Your page rendered like the screenshot. The shell reports these issues:\n{reported}\n\n"
            "Check readability and agreement with the ask. Does any visible number, mark, label "
            "or solved step give away the answer to the child's question? Lint does not detect answer leaks. "
            "Answer OK if right, otherwise only the corrected page body.")
        answer, _ = await self._call_model(self.system_prompt(), user, look_png=png)
        answer = strip_fences(answer)
        record_active("screen_look", {"fixed": bool(answer and answer != "OK")})
        if not answer or answer == "OK":
            return None
        return answer

    async def _retry_with_lint(self, ask: str, body: str, lint: list[str],
                               width: int, height: int) -> str | None:
        """One correction with the page source, the pane and the exact lint."""
        from .debug_log import record_active

        problems = "\n".join(f"- {text}" for text in lint)
        user = (
            f"The tutor's ask was: {ask}\n\n"
            f"{pane_context(width, height)}\n\n"
            f"Your page body (source):\n\n{body}\n\n"
            f"It still reports these problems after the look pass:\n{problems}\n\n"
            "Fix exactly these in the page and keep what already works. "
            "Answer with the corrected full page body only (no explanation).")
        answer, _ = await self._call_model(self.system_prompt(), user)
        answer = strip_fences(answer)
        record_active("screen_lint_retry", {"fixed": bool(answer)})
        return None if answer == "OK" or classify_answer(answer) == "patch" else (answer or None)

    # ---- real model call -------------------------------------------------

    def _default_model_call(self, system: str, user: str,
                            images: list[str], look_png: bytes | None) -> str:
        """Blocking call, run in a thread. Gemini uses Google; other models use Go.
        There is no provider fallback. SCREEN_THINKING controls DeepSeek's toggle."""
        from openai import OpenAI

        from .config import USER_AGENT

        spec = self.model_spec()
        model, api, effort = spec["model"], spec["api"], spec["reasoning"]
        gemini = model.lower().startswith("gemini-")
        key_name = "GEMINI_API_KEY" if gemini else "OPENCODE_GO_API_KEY"
        key = os.environ.get(key_name, "")
        if not key:
            raise RuntimeError(f"{key_name} is empty: run through server/bin/with-env")
        headers = {"User-Agent": USER_AGENT}
        if not gemini:
            headers["x-opencode-session"] = self.session_id
        client = OpenAI(api_key=key, base_url=GEMINI_BASE_URL if gemini else SCREEN_BASE_URL,
                        default_headers=headers,
                        timeout=40.0, max_retries=0)
        image_url = None
        if look_png:
            import base64

            mime = "image/jpeg" if look_png.startswith(b"\xff\xd8\xff") else (
                "image/webp" if look_png[:4] == b"RIFF" and look_png[8:12] == b"WEBP" else "image/png")
            image_url = f"data:{mime};base64,{base64.b64encode(look_png).decode()}"
        if api == "chat":
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})
            if look_png:
                content.append({"type": "image_url",
                                "image_url": {"url": image_url}})
            reasoning: dict[str, Any] = {}
            if spec.get("thinking"):
                reasoning["extra_body"] = {"thinking": {"type": spec["thinking"]}}
            if spec.get("thinking") != "disabled":
                reasoning["reasoning_effort"] = effort
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}],  # type: ignore[arg-type]
                **reasoning,
            )
            return (response.choices[0].message.content or "").strip()
        from openai.types import Reasoning

        if images or look_png:
            parts: list[dict[str, Any]] = [{"type": "input_text", "text": user}]
            for url in images:
                parts.append({"type": "input_image", "image_url": url})
            if look_png:
                parts.append({"type": "input_image", "image_url": image_url})
            response = client.responses.create(
                model=model, instructions=system,
                input=[{"role": "user", "content": parts}],  # type: ignore[arg-type]
                reasoning=Reasoning(effort=effort), store=False,  # type: ignore[arg-type]
            )
        else:
            response = client.responses.create(
                model=model, instructions=system, input=user,
                reasoning=Reasoning(effort=effort), store=False,  # type: ignore[arg-type]
            )
        return (response.output_text or "").strip()

    # ---- real renderer ----------------------------------------------------

    async def _default_render_page(self, body: str, patch: str | None,
                                   width: int, height: int) -> tuple[bytes, list]:
        """Render with the shell the way the app does, in headless Chromium.
        One browser per session, shared across jobs; pages open and close.
        The browser is warmed up at session start (see warmup()); a first job
        that arrives before the warmup finished still launches it here."""
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._pw.chromium.launch()
        page = await self._browser.new_page(viewport={"width": width, "height": height}, reduced_motion="reduce")
        try:
            await page.set_content(screenkit.host_page(screenkit.compose(body)))
            # The inner srcdoc frame may not exist on the very first tick;
            # wait for it instead of falling back to the outer document,
            # which never reports otReady and would cost a 30 s timeout.
            frame = None
            for _ in range(100):
                if len(page.frames) > 1:
                    frame = page.frames[1]
                    break
                await page.wait_for_timeout(50)
            if frame is None:
                frame = page.main_frame
            await frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            info = await frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            issues = list(info.get("issues") or [])
            seen = len(issues)
            if patch:
                # Replay distinct batches: removals must finish before the next patch.
                # Reduced motion makes the preview final immediately, saving the old 1 s wait.
                for change in [*self.visible_patches, patch]:
                    try:
                        patch_issues = await frame.evaluate("(p) => ot.patch(p)", change)
                        issues.extend(patch_issues or [])
                    except Exception as error:  # noqa: BLE001 - rejected before child delivery
                        issues.append(f"patch failed: {type(error).__name__}")
                        break
                    await frame.evaluate("""async () => {
                        for (const a of document.getAnimations()) {
                            if (Number.isFinite(a.effect.getComputedTiming().endTime)) a.finish();
                        }
                        await new Promise(requestAnimationFrame);
                    }""")
                # A patch-added image is still fetching when ot.patch reports:
                # the boot wait above covered the first render, not this one.
                # Hold the screenshot (bounded) until its bitmap arrived, so the
                # tutor judges the picture the child will see, not an empty box.
                try:
                    await frame.wait_for_function(
                        "() => ![...document.querySelectorAll('ot-image img')]"
                        ".some(i => i.src && !i.complete)",
                        timeout=5000)
                except Exception:  # noqa: BLE001 - preserve the page and report the incomplete preview
                    issues.append({"kind": "image", "msg": "patch image still loading after 5 seconds"})
                late = await frame.evaluate("(n) => ot.issues.slice(n)", seen)
                issues.extend(item for item in late or [] if item not in issues)
            shot = await page.screenshot()
            return bytes(shot), issues
        finally:
            await page.close()
