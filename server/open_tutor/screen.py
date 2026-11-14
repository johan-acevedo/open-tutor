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
COMMAND_CODE_BASE_URL = "https://api.commandcode.ai/provider/v1"
JOB_TIMEOUT_S = 20.0
# A fallback call that cannot run this long is not started: the page could not
# be rendered and delivered in what is left anyway. The job then fails as it
# does with no fallback configured.
FALLBACK_MIN_S = 2.0
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


def _accepts_first_text(fn: Callable[..., Any]) -> bool:
    """Whether a model-call seam function takes an ``on_first_text`` keyword.

    The real implementation streams and declares it; plain fakes (including
    ``AsyncMock`` without a spec, which exposes no signature) are called the
    old way and their completion counts as their first text."""
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "on_first_text" in parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
    )


def _screen_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# First-text hedge: how long the primary screen call gets before the same call
# also starts on SCREEN_FALLBACK. Empty means the #64 flat-timeout failover
# instead (SCREEN_PRIMARY_TIMEOUT_S); anything unparseable is the default.
DEFAULT_SCREEN_HEDGE_AFTER_S = 5.0


def _screen_hedge_after_s() -> float | None:
    """Seconds before a slow screen call is hedged, or ``None`` for the legacy
    flat-timeout failover (``SCREEN_HEDGE_AFTER_S`` empty)."""
    raw = os.environ.get("SCREEN_HEDGE_AFTER_S")
    if raw is None:
        return DEFAULT_SCREEN_HEDGE_AFTER_S
    raw = str(raw).strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_SCREEN_HEDGE_AFTER_S


def default_model_spec() -> dict[str, str]:
    """Which screen model and reasoning level this session uses (env only)."""
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


def default_fallback_spec() -> dict[str, str] | None:
    """The backup model, from ``SCREEN_FALLBACK`` (empty: none, today's behaviour).

    ``cc`` is the same Muse model family on Command Code (``meta/`` + the Go
    model id), reached over the Responses API with the same reasoning level.
    Anything else -- an unknown name, or ``cc`` with a non-Muse screen model --
    raises instead of silently running unprotected."""
    name = _screen_env("SCREEN_FALLBACK", "").strip().lower()
    if not name:
        return None
    if name != "cc":
        raise ValueError("SCREEN_FALLBACK must be empty or 'cc'")
    primary = default_model_spec()
    model = primary["model"]
    if not model.lower().startswith("muse-"):
        raise ValueError(
            f"SCREEN_FALLBACK=cc needs a Muse screen model, not {model!r} "
            "(today: muse-spark-1.3-contributor)")
    return {"model": f"meta/{model}", "api": primary["api"],
            "reasoning": primary["reasoning"]}


def _spec_provider(spec: dict[str, str]) -> str:
    """Short provider label for meta.json and the debug trail (never a key)."""
    model = spec.get("model", "").lower()
    if model.startswith("meta/"):
        return "cc"
    if model.startswith("gemini-"):
        return "google"
    return "go"


def _fallback_key_name(spec: dict[str, str]) -> str:
    """Which backend key a backup spec needs (never the key itself)."""
    provider = _spec_provider(spec)
    if provider == "cc":
        return "COMMAND_CODE_API_KEY"
    if provider == "google":
        return "GEMINI_API_KEY"
    return "OPENCODE_GO_API_KEY"


class Screen:
    """Follows one session's lesson and renders screen pages in the background."""

    def __init__(
        self,
        learner: dict[str, Any] | None,
        pages_dir: Path | str,
        *,
        session_id: str = "screen",
        model_call: ModelCall | None = None,
        fallback_call: ModelCall | None = None,
        render_page: RenderPage | None = None,
        get_pane_size: Callable[[], tuple[int, int]] | None = None,
        timeout: float = JOB_TIMEOUT_S,
    ) -> None:
        self.learner = learner or {}
        self.pages_dir = Path(pages_dir)
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self._model_call = model_call or self._default_model_call
        # The backup model call (Command Code when SCREEN_FALLBACK=cc). None means
        # the default backup path; tests inject a fake here just like model_call.
        self._fallback_call = fallback_call
        self._render_page = render_page or self._default_render_page
        # Per-job failover tracking (one job runs at a time; _run_job resets these).
        self._job_id: str | None = None
        self._job_deadline: float | None = None
        self._job_write_provider: str | None = None
        self._job_failover: dict[str, str] | None = None
        self._job_hedged = False
        self._job_ttft_s: float | None = None
        self._get_pane_size = get_pane_size or (lambda: (1366, 768))
        self.timeout = timeout
        # Backup credentials are validated once, here: a fallback whose key is
        # missing is disabled with one clear warning instead of failing every
        # job, and a primary failure then surfaces as itself instead of being
        # replaced by the fallback's config error. An injected ``fallback_call``
        # (tests) needs no key. Shape errors (unknown name, non-Muse model)
        # still fail loudly at the first call, as before.
        self._fallback_disabled: str | None = None
        if _screen_env("SCREEN_FALLBACK", "").strip() and self._fallback_call is None:
            try:
                spec = default_fallback_spec()
            except ValueError:
                spec = None  # shape errors stay loud at the first call
            if spec is not None and not os.environ.get(_fallback_key_name(spec), "").strip():
                self._fallback_disabled = (
                    f"{_fallback_key_name(spec)} is empty: "
                    f"SCREEN_FALLBACK={_screen_env('SCREEN_FALLBACK', '').strip()} disabled; "
                    "the primary serves every call alone"
                )
                log.warning("screen backup disabled: %s", self._fallback_disabled)
        # Per-call stats for analytics (kind, serving provider, hedge use and
        # first-text times; never prompts or answers).
        self._call_stats: list[dict[str, Any]] = []
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

    async def _invoke(self, fn: ModelCall, system: str, user: str,
                    images: list[str], look_png: bytes | None,
                    on_first_text: Callable[[], None] | None = None) -> str:
        """Run one model-call seam function and return its full text.

        The seam stays ``(system, user, images, look_png) -> text`` so tests keep
        injecting plain fakes. The real implementation streams and signals its
        first output text through ``on_first_text``; a seam function that declares
        an ``on_first_text`` keyword gets it, anything else is called as before
        (and its completion counts as its first text)."""
        if inspect.iscoroutinefunction(fn):
            if on_first_text is not None and _accepts_first_text(fn):
                result = await fn(system, user, images, look_png, on_first_text=on_first_text)
            else:
                result = await fn(system, user, images, look_png)
        else:
            # Blocking seam doubles (tests only): off the event loop. Production
            # provider calls are async streaming and never touch a thread.
            result = await asyncio.to_thread(fn, system, user, images, look_png)
        return str(result)

    async def _run_route(self, call: ModelCall, system: str, user: str,
                         images: list[str], look_png: bytes | None,
                         first: asyncio.Event, holder: dict[str, float],
                         base: float | None = None) -> tuple[str, float]:
        """Run one side of a (possibly hedged) call; signal its first text.

        Returns ``(full text, total seconds)``. A streaming call fires ``first``
        from its first output text; a plain seam call fires it on completion.
        ``base`` is the perf-counter baseline the first-text time is measured
        from; a hedged call passes its own start so every route's timing is on
        the original call's clock instead of omitting the hedge wait.
        """
        t0 = time.monotonic()
        base = time.perf_counter() if base is None else base
        fired = False

        def on_first_text() -> None:
            nonlocal fired
            if not fired:
                fired = True
                holder["t"] = time.perf_counter() - base
                first.set()

        text = await self._invoke(call, system, user, images, look_png,
                                  on_first_text=on_first_text)
        if not fired:
            # A non-streaming call (plain seam function): completion is its text.
            holder["t"] = time.perf_counter() - base
            first.set()
        return text, time.monotonic() - t0

    async def _call_model(self, system: str, user: str,
                          look_png: bytes | None = None,
                          kind: str = "write",
                          budget_s: float | None = None) -> tuple[str, float]:
        """One model call (``kind``: write|look|retry|image), hedged when armed.

        Without ``SCREEN_FALLBACK`` this is today's single-provider call. With it,
        the primary's first output text is awaited for ``SCREEN_HEDGE_AFTER_S``
        (default 5 s); when nothing arrives the same call starts on the backup
        and the first side to produce text serves the whole call, the other
        cancelled and closed. An empty ``SCREEN_HEDGE_AFTER_S`` keeps the #64
        flat-timeout failover instead. ``budget_s`` is the calling step's own
        remaining seconds (look/retry): the hedge deadline is capped so both
        attempts fit inside it, and no hedge starts with under 2 s left.
        Cancellation still propagates, so the job limit in ``_pump`` keeps
        working; provider calls are async and streaming, so a cancelled call
        closes its stream instead of outliving its job in a thread.
        """
        t0 = time.monotonic()
        fallback = self._fallback_ready()
        if fallback is None:
            first: asyncio.Event = asyncio.Event()
            holder: dict[str, float] = {}
            try:
                result = await self._run_route(self._model_call, system, user,
                                               self._homework_images(), look_png, first, holder)
            except Exception as error:
                self._note_call(kind, _spec_provider(self.model_spec()), hedged=False,
                                ttft_s=None, loser="none", error=type(error).__name__)
                raise
            text, _elapsed = result
            self._note_provider(kind, _spec_provider(self.model_spec()), failed=False)
            self._note_call(kind, _spec_provider(self.model_spec()), hedged=False,
                            ttft_s=holder.get("t"), loser="none")
            return text, time.monotonic() - t0
        hedge_after = _screen_hedge_after_s()
        if hedge_after is None:
            return await self._call_model_legacy(system, user, look_png, kind, t0, budget_s)
        return await self._call_model_hedged(system, user, look_png, kind, t0,
                                             fallback, hedge_after, budget_s)

    async def _call_model_legacy(self, system: str, user: str,
                                 look_png: bytes | None, kind: str, t0: float,
                                 budget_s: float | None) -> tuple[str, float]:
        """The #64 flat-timeout failover (``SCREEN_HEDGE_AFTER_S`` empty).

        The primary runs under ``SCREEN_PRIMARY_TIMEOUT_S``, fitted inside the
        calling step's own budget when one is passed; on any error or timeout
        the fallback gets the remaining job budget. Never hedged."""
        fallback = self._fallback_ready()
        assert fallback is not None  # _call_model only routes here with a backup
        primary_provider = _spec_provider(self.model_spec())
        images = self._homework_images()
        first: asyncio.Event = asyncio.Event()
        holder: dict[str, float] = {}
        primary_timeout = _screen_float("SCREEN_PRIMARY_TIMEOUT_S", 10.0)
        if primary_timeout <= 0:
            raise ValueError("SCREEN_PRIMARY_TIMEOUT_S must be positive")
        if budget_s is not None:
            # Fit both attempts inside the step: the primary gets what is left
            # after the fallback floor, at least a second to answer.
            primary_timeout = min(primary_timeout, max(1.0, budget_s - FALLBACK_MIN_S))
        try:
            text, _elapsed = await asyncio.wait_for(
                self._run_route(self._model_call, system, user, images, look_png,
                                first, holder),
                timeout=primary_timeout,
            )
            self._note_provider(kind, primary_provider, failed=False)
            self._note_call(kind, primary_provider, hedged=False,
                            ttft_s=holder.get("t"), loser="none")
            return text, time.monotonic() - t0
        except asyncio.CancelledError:
            raise
        except Exception as primary_error:  # noqa: BLE001 - failover or fail as today
            error_class = type(primary_error).__name__
            remaining = self._fallback_budget()
            if budget_s is not None:
                remaining = min(remaining, budget_s)
            if remaining < FALLBACK_MIN_S:
                # Too little time left for a backup call to deliver.
                self._note_call(kind, None, hedged=False, ttft_s=None,
                                loser="none", error=error_class)
                raise
            log.warning("screen %s call failed on %s (%s); trying the fallback with %.1f s left",
                        kind, self._job_id, error_class, remaining)
            fallback_first: asyncio.Event = asyncio.Event()
            fallback_holder: dict[str, float] = {}
            try:
                if self._fallback_call is not None:
                    text, _elapsed = await asyncio.wait_for(
                        self._run_route(self._fallback_call, system, user, images,
                                       look_png, fallback_first, fallback_holder),
                        timeout=remaining,
                    )
                else:
                    text, _fallback_first_s = await asyncio.wait_for(
                        self._stream_spec(fallback, system, user, images, look_png,
                                        self._track_first(fallback_first, fallback_holder)),
                        timeout=remaining,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as fallback_error:  # noqa: BLE001 - the job fails as today
                log.warning("screen %s fallback failed (%s) after primary %s",
                            kind, type(fallback_error).__name__, error_class)
                self._note_call(kind, None, hedged=False, ttft_s=None,
                                loser="error", error=error_class)
                raise primary_error from fallback_error
            self._note_provider(kind, _spec_provider(fallback), failed=True,
                                error_class=error_class)
            self._note_call(kind, _spec_provider(fallback), hedged=False,
                            ttft_s=fallback_holder.get("t"), loser="error")
            return text, time.monotonic() - t0

    def _track_first(self, event: asyncio.Event,
                     holder: dict[str, float],
                     base: float | None = None) -> Callable[[], None]:
        """An ``on_first_text`` sink backed by an event and a timing holder.

        ``base`` is the perf-counter baseline the timing is measured from; a
        hedged call passes its own start so the backup's wait is included."""
        base = time.perf_counter() if base is None else base
        fired = False

        def on_first_text() -> None:
            nonlocal fired
            if not fired:
                fired = True
                holder["t"] = time.perf_counter() - base
                event.set()

        return on_first_text

    async def _call_model_hedged(self, system: str, user: str,
                                 look_png: bytes | None, kind: str, t0: float,
                                 fallback: dict[str, str], hedge_after: float,
                                 budget_s: float | None) -> tuple[str, float]:
        """Race the same call on both providers; first output text wins.

        The secondary starts when the primary produced no text within the hedge
        deadline; the winner serves the whole call and the loser is cancelled
        and its stream closed. One attempt per side: the hedge is the retry, so
        attempts never exceed today's worst case, and an already attempted
        route is never requested again within one call. A winner that dies
        mid-answer gets one failover-like attempt on the other side, but only
        when that side was never attempted. Every attempt runs under the
        call's original absolute deadline, and a caller cancellation always
        propagates instead of starting a backup that would outlive it."""
        images = self._homework_images()
        primary_provider = _spec_provider(self.model_spec())
        fallback_provider = _spec_provider(fallback)
        limit = self._fallback_budget()
        if budget_s is not None:
            limit = min(limit, budget_s)
        # One clock for every route's first-text time: the backup's timing
        # includes the hedge wait instead of starting at zero on its own start.
        call_base = time.perf_counter()
        if limit < FALLBACK_MIN_S:
            # Too little time left for a backup call to deliver: serve alone.
            first: asyncio.Event = asyncio.Event()
            holder: dict[str, float] = {}
            try:
                text, _elapsed = await self._run_route(
                    self._model_call, system, user, images, look_png, first, holder,
                    base=call_base)
            except Exception as error:
                self._note_call(kind, primary_provider, hedged=False,
                                ttft_s=None, loser="none", error=type(error).__name__)
                raise
            self._note_provider(kind, primary_provider, failed=False)
            self._note_call(kind, primary_provider, hedged=False,
                            ttft_s=holder.get("t"), loser="none")
            return text, time.monotonic() - t0
        # Both attempts must fit inside the step: the hedge fires at the deadline
        # or halfway through what is left, whichever comes first.
        hedge_deadline = min(hedge_after, limit / 2)
        # The absolute monotonic deadline for every attempt in this call.
        deadline = t0 + limit
        p_first: asyncio.Event = asyncio.Event()
        p_holder: dict[str, float] = {}
        s_first: asyncio.Event = asyncio.Event()
        s_holder: dict[str, float] = {}
        attempted = {"primary"}
        p_task = asyncio.create_task(
            self._run_route(self._model_call, system, user, images, look_png,
                            p_first, p_holder, base=call_base),
            name=f"screen-hedge-primary-{kind}")
        s_task: asyncio.Task[tuple[str, float]] | None = None
        errors: dict[str, BaseException] = {}
        primary_error_class: str | None = None
        try:
            try:
                await asyncio.wait_for(p_first.wait(), timeout=max(0.0, hedge_deadline))
            except TimeoutError:
                pass
            if p_first.is_set():
                # The primary produced text before the deadline: no hedge.
                winner: str | None = "primary"
            else:
                winner = None
                if p_task.done():
                    try:
                        p_task.result()
                    except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                        raise
                    except BaseException as error:
                        # The primary is already dead; the backup serves alone.
                        errors["primary"] = error
                        primary_error_class = type(error).__name__
            if winner is None:
                s_task = self._start_screen_secondary(
                    fallback, system, user, images, look_png, kind, s_first, s_holder,
                    base=call_base)
                attempted.add("secondary")
                winner = await self._race_screen_first(
                    p_task, s_task, p_first, s_first, p_holder, s_holder, errors)
                if winner is None:
                    # Both sides failed before any text: today's error path.
                    # The primary's error surfaces when both failed, else the
                    # one side that actually errored (no eager ``.get``
                    # default: it would raise ``KeyError`` when only the
                    # secondary failed).
                    if "primary" in errors:
                        error = errors["primary"]
                    else:
                        error = errors["secondary"]
                    assert error is not None
                    if "primary" in errors:
                        primary_error_class = type(errors["primary"]).__name__
                    self._note_call(kind, None, hedged=True, ttft_s=None,
                                    loser="error", error=type(error).__name__)
                    raise error
            assert s_task is not None or winner == "primary"
            if winner == "primary":
                loser, loser_task = "secondary", s_task
            else:
                loser, loser_task = "primary", p_task
            if loser_task is not None:
                loser_task.cancel()
                try:
                    await loser_task
                except BaseException:  # noqa: BLE001 - already recorded or cancelled
                    pass
            if loser == "primary" and "primary" in errors:
                primary_error_class = type(errors["primary"]).__name__
            winner_task = p_task if winner == "primary" else s_task
            assert winner_task is not None
            try:
                # Bounded by the call's original absolute deadline: a winner
                # that never finishes must not outlive the caller's timeout.
                winner_text, _winner_elapsed = await asyncio.wait_for(
                    winner_task, timeout=max(0.0, deadline - time.monotonic()))
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                # The caller went away: propagate at once instead of starting
                # a backup that would outlive the caller's timeout.
                raise
            except BaseException as winner_error:
                # The winner died mid-answer: one failover-like attempt on the
                # other side, unless that side was already attempted in this
                # call (a hedged race tried both; restarting the cancelled
                # loser would be a second request on one route).
                if winner == "primary":
                    primary_error_class = type(winner_error).__name__
                if loser in errors or loser in attempted:
                    self._note_call(kind, None, hedged=True, ttft_s=None,
                                    loser="error", error=type(winner_error).__name__)
                    raise winner_error
                remaining = deadline - time.monotonic()
                if remaining < FALLBACK_MIN_S:
                    # No time left for a backup call to deliver.
                    self._note_call(kind, None, hedged=True, ttft_s=None,
                                    loser="error", error=type(winner_error).__name__)
                    raise winner_error
                # A fresh request needs a fresh first-text signal: the old event
                # may already be set by the cancelled attempt.
                other_first, other_holder = asyncio.Event(), {}
                if loser == "secondary":
                    other_task: asyncio.Task[tuple[str, float]] = self._start_screen_secondary(
                        fallback, system, user, images, look_png, kind,
                        other_first, other_holder, base=call_base)
                else:
                    other_task = asyncio.create_task(
                        self._run_route(self._model_call, system, user, images,
                                       look_png, other_first, other_holder,
                                       base=call_base),
                        name=f"screen-hedge-restart-{kind}")
                try:
                    winner_text, _winner_elapsed = await asyncio.wait_for(
                        other_task, timeout=remaining)
                except (asyncio.CancelledError, KeyboardInterrupt, SystemExit):
                    raise
                except BaseException as other_error:
                    self._note_call(kind, None, hedged=True, ttft_s=None,
                                    loser="error", error=type(winner_error).__name__)
                    raise winner_error from other_error
                winner = loser
                winner_first_t = other_holder.get("t")
            else:
                winner_first_t = (p_holder if winner == "primary" else s_holder).get("t")
            winner_provider = primary_provider if winner == "primary" else fallback_provider
            served_by_fallback = winner == "secondary"
            self._note_provider(kind, winner_provider, failed=served_by_fallback,
                                error_class=primary_error_class or "")
            hedged_race = s_task is not None
            if loser == "secondary" and s_task is None:
                loser_state = "none"  # the secondary never started
            else:
                loser_state = "error" if loser in errors else "cancelled"
            if self._job_id is not None and hedged_race:
                from .debug_log import record_active

                record_active("screen_hedge", {
                    "job": self._job_id, "kind": kind, "winner": winner_provider,
                    "ttft_s": None if winner_first_t is None else round(winner_first_t, 3),
                    "loser": loser_state,
                })
            self._note_call(kind, winner_provider, hedged=hedged_race,
                            ttft_s=winner_first_t, loser=loser_state)
            return winner_text, time.monotonic() - t0
        finally:
            for task in (p_task, s_task):
                if task is not None and not task.done():
                    task.cancel()
            for task in (p_task, s_task):
                if task is not None:
                    try:
                        await task
                    except BaseException:  # noqa: BLE001 - recorded above or cancelled
                        pass

    def _start_screen_secondary(self, fallback: dict[str, str], system: str, user: str,
                                images: list[str], look_png: bytes | None, kind: str,
                                first: asyncio.Event, holder: dict[str, float],
                                base: float | None = None,
                                ) -> "asyncio.Task[tuple[str, float]]":
        """Start the identical call on the backup provider.

        ``base`` is the call's first-text clock (see ``_call_model_hedged``).
        """
        if self._fallback_call is not None:
            call = self._run_route(self._fallback_call, system, user, images,
                                   look_png, first, holder, base=base)
        else:
            async def _real() -> tuple[str, float]:
                text, _first_s = await self._stream_spec(
                    fallback, system, user, images, look_png,
                    self._track_first(first, holder, base=base))
                return text, 0.0
            call = _real()
        return asyncio.create_task(call, name=f"screen-hedge-secondary-{kind}")

    async def _race_screen_first(
        self,
        p_task: "asyncio.Task[tuple[str, float]]",
        s_task: "asyncio.Task[tuple[str, float]]",
        p_first: asyncio.Event, s_first: asyncio.Event,
        p_holder: dict[str, float], s_holder: dict[str, float],
        errors: dict[str, BaseException],
    ) -> str | None:
        """Wait for the first output text from either side; ``None`` when both
        failed before any text. A side that errored stops being waited on."""
        p_wait = asyncio.create_task(p_first.wait(), name="screen-hedge-wait-primary")
        s_wait = asyncio.create_task(s_first.wait(), name="screen-hedge-wait-secondary")
        try:
            while True:
                pt = p_holder.get("t")
                st = s_holder.get("t")
                if pt is not None and (st is None or pt <= st):
                    return "primary"
                if st is not None:
                    return "secondary"
                for side, task in (("primary", p_task), ("secondary", s_task)):
                    if task.done() and side not in errors:
                        try:
                            task.result()
                        except BaseException as error:
                            errors[side] = error
                if set(errors) == {"primary", "secondary"}:
                    return None
                pending = {t for t in (p_task, s_task, p_wait, s_wait) if not t.done()}
                if not pending:
                    return None  # both runners done with no text: both errored
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (p_wait, s_wait):
                if not task.done():
                    task.cancel()
                try:
                    await task
                except BaseException:  # noqa: BLE001 - waiter, nothing to record
                    pass

    def _fallback_budget(self) -> float:
        """Seconds the fallback may spend without pushing past the job limit."""
        if self._job_deadline is None:
            return _screen_float("SCREEN_PRIMARY_TIMEOUT_S", 10.0)
        return self._job_deadline - time.monotonic()

    def _note_call(self, kind: str, provider: str | None, *, hedged: bool,
                   ttft_s: float | None, loser: str,
                   error: str | None = None) -> None:
        """Remember one model call for analytics (never prompts or answers)."""
        self._call_stats.append({
            "kind": kind, "provider": provider, "hedged": hedged,
            "ttft_s": None if ttft_s is None else round(ttft_s, 3),
            "loser": loser, **({"error": error} if error is not None else {}),
        })
        if kind == "write":
            self._job_hedged = hedged
            self._job_ttft_s = None if ttft_s is None else round(ttft_s, 3)

    def screen_stats_summary(self) -> dict[str, Any]:
        """Per-session screen call stats for ``tutor_session_ended``.

        Counts, hedges and first-text timings per call kind, plus which provider
        served each call. Never prompts or answers."""
        from .analytics import summarize_screen_calls

        summary = summarize_screen_calls(self._call_stats)
        return {
            "screen_calls_total": summary["calls_total"],
            "screen_hedged_calls": summary["hedged_calls"],
            "screen_provider_wins": summary["provider_wins"],
            "screen_calls": summary["calls"],
        }

    def _note_provider(self, kind: str, provider: str, *, failed: bool,
                       error_class: str = "") -> None:
        """Remember who served a model call for meta.json and the debug trail."""
        from .debug_log import record_active

        if self._job_write_provider is None and kind == "write":
            self._job_write_provider = provider
        if failed:
            if self._job_failover is None:
                self._job_failover = {"kind": kind, "provider": provider,
                                      "primary_error": error_class}
            record_active("screen_failover", {"job": self._job_id, "kind": kind,
                                                "to": provider, "error": error_class})

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

    def _fallback_ready(self) -> dict[str, str] | None:
        """The backup spec when hedging/failover may actually use it.

        ``None`` when no fallback is configured, or when setup disabled it for a
        missing key (warned once there). Shape errors still raise loudly."""
        if self._fallback_disabled is not None:
            return None
        return self.fallback_spec()

    def model_spec(self) -> dict[str, str]:
        """Which screen model and reasoning level this session uses."""
        return default_model_spec()

    def fallback_spec(self) -> dict[str, str] | None:
        """The backup model, from ``SCREEN_FALLBACK`` (empty: none, today's behaviour).

        ``cc`` is the same Muse model family on Command Code (``meta/`` + the Go
        model id), reached over the Responses API with the same reasoning level.
        Anything else -- an unknown name, or ``cc`` with a non-Muse screen model --
        raises instead of silently running unprotected."""
        return default_fallback_spec()

    async def _run_job(self, job_id: str, ask: str) -> None:
        from .debug_log import record_active

        t0 = time.monotonic()
        self._job_id = job_id
        self._job_deadline = t0 + self.timeout
        self._job_write_provider = None
        self._job_failover = None
        self._job_hedged = False
        self._job_ttft_s = None
        if not ask:
            await self._fail(job_id, "The screen got an empty ask. Explain in words instead, briefly.")
            return
        system = self.system_prompt()
        user = self._build_user_text(ask)
        generation_time = self.timeout - min(2.0, self.timeout * 0.2)
        answer, model_s = await asyncio.wait_for(
            self._call_model(system, user, budget_s=self._fallback_budget()),
            timeout=generation_time)
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
                              **self._provider_meta(),
                              "model_s": round(model_s, 2), "render_s": round(render_s, 2),
                              "total_s": round(total_s, 2), "issues": issues,
                              "delivered": not errors,
                              "image_s": round(images.seconds, 2), "image_reviews": images.events})
        record_active("screen_patch", {"job": job_id, "page": visible.page_id,
                                       "total_s": round(total_s, 2), "issues": issues,
                                       "delivered": not errors,
                                       **self._provider_meta()})
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
                    t0, reserve_s,
                    lambda budget: self._look_once(ask, body, png, issues, width, height, budget),
                    target_s=look_target)
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
                    t0, reserve_s,
                    lambda budget: self._retry_with_lint(ask, body, leftover, width, height, budget))
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
                              **self._provider_meta(),
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
                                      "retry_applied": repair["retry_applied"],
                                      **self._provider_meta()})
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

    def _provider_meta(self) -> dict[str, Any]:
        """Who served this job's model calls: the write-call provider, whether
        any call failed over (with the primary error class when one errored),
        whether the write call was hedged, and its first-text time. Never a key."""
        meta: dict[str, Any] = {"provider": self._job_write_provider or _spec_provider(self.model_spec()),
                                "failover": self._job_failover is not None,
                                "hedged": self._job_hedged}
        if self._job_failover is not None and self._job_failover.get("primary_error"):
            meta["primary_error"] = self._job_failover["primary_error"]
        if self._job_ttft_s is not None:
            meta["ttft_s"] = self._job_ttft_s
        if self._fallback_disabled is not None:
            meta["fallback_disabled"] = True
        return meta

    def _image_job(self, ask: str, t0: float) -> PageImages:
        async def review(user: str, image: bytes | None, _deadline: float = 0.0) -> str:
            text, _ = await self._call_model(
                "Choose an educational image for a Swedish school child. Inspect the actual picture with the lesson context. "
                "Return only the requested JSON decision, reason and a text/HTML alternative if rejected.", user, image,
                kind="image", budget_s=max(0.0, _deadline - time.monotonic()))
            return text

        deadline = min(time.monotonic() + IMAGE_BUDGET_S,
                       t0 + min(self.timeout, PAGE_TARGET_S) - FINAL_RENDER_RESERVE_S - DELIVERY_RESERVE_S)

        async def review_with_deadline(user: str, image: bytes | None) -> str:
            return await review(user, image, deadline)

        return PageImages(self._build_user_text(ask), review_with_deadline, deadline)

    def _time_left(self, t0: float) -> float:
        """Seconds until the job limit; optional work is spent from this."""
        return self.timeout - (time.monotonic() - t0)

    async def _bounded(self, t0: float, reserve_s: float,
                       make_call: Callable[[float], Awaitable[Any]], *, target_s: float | None = None
                       ) -> tuple[Any, float, str]:
        """Run one optional model step inside the job budget; it never raises.
        Returns (result, seconds, why-not), with why-not empty on success.

        ``make_call`` receives the same capped budget the outer timeout
        enforces, so a hedged step plans both attempts inside a deadline it
        can actually meet instead of being cut before the backup can start."""
        started = time.monotonic()
        try:
            remaining = self._time_left(t0) - reserve_s
            if target_s is not None:
                remaining = min(remaining, target_s - (started - t0) - reserve_s)
            budget = max(0.0, min(OPTIONAL_STEP_LIMIT_S, remaining))
            result = await asyncio.wait_for(make_call(budget),
                                            timeout=max(0.001, budget))
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
                         width: int, height: int, budget_s: float | None = None) -> str | None:
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
        answer, _ = await self._call_model(self.system_prompt(), user, look_png=png,
                                           kind="look", budget_s=budget_s)
        answer = strip_fences(answer)
        record_active("screen_look", {"fixed": bool(answer and answer != "OK")})
        if not answer or answer == "OK":
            return None
        return answer

    async def _retry_with_lint(self, ask: str, body: str, lint: list[str],
                               width: int, height: int, budget_s: float | None = None) -> str | None:
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
        answer, _ = await self._call_model(self.system_prompt(), user, kind="retry",
                                           budget_s=budget_s)
        answer = strip_fences(answer)
        record_active("screen_lint_retry", {"fixed": bool(answer)})
        return None if answer == "OK" or classify_answer(answer) == "patch" else (answer or None)

    # ---- real model call -------------------------------------------------

    async def _default_model_call(self, system: str, user: str,
                                 images: list[str], look_png: bytes | None,
                                 on_first_text: Callable[[], None] | None = None) -> str:
        """Async streaming call. Gemini uses Google, `meta/` models use Command
        Code, other models use Go. SCREEN_THINKING controls DeepSeek's toggle.

        The call streams so its first output text is observable for the hedge;
        the stream is always closed, so a cancelled call never outlives its job
        in a thread (the old blocking client is gone). The transport is shared
        per host with a long keep-alive (see http_clients.py)."""
        text, _first_s = await self._stream_spec(
            self.model_spec(), system, user, images, look_png, on_first_text)
        return text

    async def _stream_spec(self, spec: dict[str, str], system: str, user: str,
                           images: list[str], look_png: bytes | None,
                           on_first_text: Callable[[], None] | None = None
                           ) -> tuple[str, float | None]:
        """Stream one provider call; returns ``(full text, seconds to first text)``.

        The first-text time is ``None`` when the answer held no text. The caller
        owns the absolute deadline (the job or step budget); the shared transport
        only carries a generous backstop. The stream is closed in a ``finally``
        so cancellation always releases the connection."""
        from openai.types import Reasoning

        from .config import USER_AGENT
        from .http_clients import shared_async_openai

        model, api, effort = spec["model"], spec["api"], spec["reasoning"]
        provider = _spec_provider(spec)
        if provider == "cc":
            key_name, base_url = "COMMAND_CODE_API_KEY", COMMAND_CODE_BASE_URL
        elif provider == "google":
            key_name, base_url = "GEMINI_API_KEY", GEMINI_BASE_URL
        else:
            key_name, base_url = "OPENCODE_GO_API_KEY", SCREEN_BASE_URL
        key = os.environ.get(key_name, "")
        if not key:
            raise RuntimeError(f"{key_name} is empty: run through server/bin/with-env")
        client = shared_async_openai(base_url, key, USER_AGENT)
        # Go asks for a stable session id; Command Code tolerates the header.
        extra_headers = {} if provider == "google" else {"x-opencode-session": self.session_id}
        image_url = None
        if look_png:
            import base64

            mime = "image/jpeg" if look_png.startswith(b"\xff\xd8\xff") else (
                "image/webp" if look_png[:4] == b"RIFF" and look_png[8:12] == b"WEBP" else "image/png")
            image_url = f"data:{mime};base64,{base64.b64encode(look_png).decode()}"
        parts: list[str] = []
        announced = False

        def note_text(text: str) -> None:
            nonlocal announced
            if text:
                parts.append(text)
                if not announced:
                    announced = True
                    if on_first_text is not None:
                        on_first_text()

        t0 = time.perf_counter()
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
            stream = await client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}],  # type: ignore[arg-type]
                stream=True,
                extra_headers=extra_headers,
                **reasoning,
            )
            try:
                async for chunk in stream:
                    for choice in chunk.choices or []:
                        note_text(choice.delta.content or "")
            finally:
                await stream.close()
        else:
            if images or look_png:
                input_parts: list[dict[str, Any]] = [{"type": "input_text", "text": user}]
                for url in images:
                    input_parts.append({"type": "input_image", "image_url": url})
                if look_png:
                    input_parts.append({"type": "input_image", "image_url": image_url})
                payload: Any = [{"role": "user", "content": input_parts}]
            else:
                payload = user
            stream = await client.responses.create(
                model=model, instructions=system, input=payload,
                reasoning=Reasoning(effort=effort), store=False,  # type: ignore[arg-type]
                stream=True,
                extra_headers=extra_headers,
            )
            try:
                async for event in stream:
                    if event.type == "response.output_text.delta":
                        note_text(event.delta or "")
            finally:
                await stream.close()
        text = ("".join(parts)).strip()
        if announced:
            first_s: float | None = time.perf_counter() - t0
        else:
            # A silent answer still carries a timing: its completion is the first
            # observable moment, which is also what a non-streaming call reports.
            first_s = time.perf_counter() - t0
            if on_first_text is not None:
                on_first_text()
        return text, first_s

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
            preview_issues = []
            if patch:
                # Replay distinct batches: removals must finish before the next patch.
                # Reduced motion makes the preview final immediately, saving the old 1 s wait.
                for change in [*self.visible_patches, patch]:
                    try:
                        await frame.evaluate("(p) => ot.patch(p)", change)
                    except Exception as error:  # noqa: BLE001 - rejected before child delivery
                        preview_issues.append(f"patch failed: {type(error).__name__}")
                        break
                    await frame.evaluate("""async () => {
                        for (const a of document.getAnimations()) {
                            if (Number.isFinite(a.effect.getComputedTiming().endTime)) a.finish();
                        }
                        await new Promise(requestAnimationFrame);
                    }""")
                # Boot covered the first render, not bitmaps added by a patch.
                # Bound the wait and retain its advisory even if final lint clears.
                try:
                    await frame.wait_for_function(
                        "() => ![...document.querySelectorAll('ot-image img')]"
                        ".some(i => i.src && !i.complete)",
                        timeout=5000)
                except Exception:  # noqa: BLE001 - deliver the preview with its limitation
                    preview_issues.append({"kind": "image", "msg": "patch image still loading after 5 seconds"})
                # A patch can repair graph labels and an image can fail late:
                # read current lint after loading, preserving renderer exceptions.
                current = await frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
                issues = list(current.get("issues") or []) + preview_issues

            shot = await page.screenshot()
            return bytes(shot), issues
        finally:
            await page.close()
