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
from typing import Any, Awaitable, Callable

log = logging.getLogger("open-tutor")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from screen.tools import prompt as screen_prompt  # noqa: E402
from screen.tools import screenkit as screenkit  # noqa: E402

SCREEN_BASE_URL = "https://opencode.ai/inference/go/openai/v1"
JOB_TIMEOUT_S = 45.0
MAX_TURNS = 40  # conversation turns kept per request; sessions run long
MAX_HOMEWORK_IMAGES = 4


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
    total_s: float = 0.0
    directory: Path | None = None


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

    def _learner_line(self) -> str:
        name = str(self.learner.get("name") or "").strip()[:40] or "eleven"
        grade = self.learner.get("grade")
        if isinstance(grade, int) and 1 <= grade <= 12:
            level = f"åk {grade}" if grade <= 9 else f"gymnasiet år {grade - 9}"
            return f"Child: {name}, {level}."
        return f"Child: {name}."

    def _build_user_text(self, ask: str) -> str:
        parts = [self._learner_line()]
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

    async def _run_job(self, job_id: str, ask: str) -> None:
        from .debug_log import record_active

        t0 = time.monotonic()
        if not ask:
            await self._fail(job_id, "The screen got an empty ask. Explain in words instead, briefly.")
            return
        system = screen_prompt.system_prompt()
        user = self._build_user_text(ask)
        answer, model_s = await self._call_model(system, user)
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
        png, issues, render_s = await self._render(visible.body, patch)
        total_s = time.monotonic() - t0
        job_dir = self._save(job_id, ask,
                             {"patch.html": patch, "patched.png": png},
                             {"job": job_id, "kind": "patch", "page": visible.page_id,
                              "model_s": round(model_s, 2), "render_s": round(render_s, 2),
                              "total_s": round(total_s, 2), "issues": issues})
        record_active("screen_patch", {"job": job_id, "page": visible.page_id,
                                       "total_s": round(total_s, 2), "issues": issues})
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
        png, issues, render_s = await self._render(body, None)
        look_s = 0.0
        if _screen_env("SCREEN_LOOK", "1") != "0":
            fixed, look_s = await self._look_once(ask, body, png, issues)
            if fixed and fixed != body:
                body = fixed
                png, issues, extra_s = await self._render(body, None)
                render_s += extra_s
        total_s = time.monotonic() - t0
        job_dir = self._save(job_id, ask,
                             {"page.html": body, "shot.png": png},
                             {"job": job_id, "kind": "page", "page": page_id,
                              "title": page_title(body, page_id),
                              "model_s": round(model_s, 2), "render_s": round(render_s, 2),
                              "look_s": round(look_s, 2), "total_s": round(total_s, 2),
                              "issues": issues})
        record_active("screen_page", {"job": job_id, "page": page_id,
                                      "total_s": round(total_s, 2), "issues": issues})
        result = PageResult(job_id=job_id, page_id=page_id,
                            title=page_title(body, page_id), body=body, png=png,
                            issues=issues, model_s=model_s, render_s=render_s,
                            look_s=look_s, total_s=total_s, directory=job_dir)
        self.pages[page_id] = result
        if self.on_page is not None:
            outcome = self.on_page(result)
            if inspect.isawaitable(outcome):
                await outcome

    async def _look_once(self, ask: str, body: str, png: bytes,
                         issues: list) -> tuple[str | None, float]:
        """Show the model its own render; it answers OK or a corrected body."""
        from .debug_log import record_active

        system = screen_prompt.system_prompt()
        reported = ", ".join(str(i) for i in issues) if issues else "none"
        user = (f"The tutor's ask was: {ask}\n\nYour page rendered like the screenshot. "
                f"The shell reports these issues: {reported}.\n\n"
                f"If the page looks good, answer with exactly: OK\n"
                f"Otherwise answer with the corrected full page body only (no explanation).")
        answer, look_s = await self._call_model(system, user, look_png=png)
        answer = strip_fences(answer)
        record_active("screen_look", {"fixed": bool(answer and answer != "OK")})
        if not answer or answer == "OK":
            return None, look_s
        return answer, look_s

    # ---- real model call -------------------------------------------------

    def _default_model_call(self, system: str, user: str,
                            images: list[str], look_png: bytes | None) -> str:
        """Call the screen model on the Go OpenAI-compatible endpoint (blocking;
        the job runs it in a thread). ``SCREEN_MODEL`` and ``SCREEN_REASONING``
        override the defaults; DeepSeek models use Chat Completions."""
        from openai import OpenAI

        from .config import USER_AGENT

        key = os.environ.get("OPENCODE_GO_API_KEY", "")
        if not key:
            raise RuntimeError("OPENCODE_GO_API_KEY is empty: run through server/bin/with-env")
        model = _screen_env("SCREEN_MODEL", "muse-spark-1.3-contributor")
        api = _screen_env("SCREEN_API", "") or ("chat" if "deepseek" in model.lower() else "responses")
        client = OpenAI(api_key=key, base_url=SCREEN_BASE_URL,
                        default_headers={"User-Agent": USER_AGENT,
                                         "x-opencode-session": self.session_id},
                        timeout=40.0, max_retries=0)
        if api == "chat":
            effort = _screen_env("SCREEN_REASONING", "") or "low"
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            for url in images:
                content.append({"type": "image_url", "image_url": {"url": url}})
            if look_png:
                import base64

                data = base64.b64encode(look_png).decode()
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{data}"}})
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": content}],  # type: ignore[arg-type]
                reasoning_effort=effort,  # type: ignore[call-arg]
            )
            return (response.choices[0].message.content or "").strip()
        from openai.types import Reasoning

        effort = _screen_env("SCREEN_REASONING", "") or "minimal"
        if images or look_png:
            import base64

            parts: list[dict[str, Any]] = [{"type": "input_text", "text": user}]
            for url in images:
                parts.append({"type": "input_image", "image_url": url})
            if look_png:
                parts.append({"type": "input_image", "image_url": (
                    f"data:image/png;base64,{base64.b64encode(look_png).decode()}")})
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
        One browser per session, shared across jobs; pages open and close."""
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        if self._browser is None or not self._browser.is_connected():
            self._browser = await self._pw.chromium.launch()
        page = await self._browser.new_page(viewport={"width": width, "height": height})
        try:
            await page.set_content(screenkit.host_page(screenkit.compose(body)))
            frame = page.frames[1] if len(page.frames) > 1 else page.main_frame
            await frame.wait_for_function(
                "() => document.documentElement.dataset.otReady === '1'", timeout=30000)
            info = await frame.evaluate("() => ({fontPx: ot.fontPx, issues: ot.issues})")
            issues = list(info.get("issues") or [])
            if patch:
                try:
                    patch_issues = await frame.evaluate("(p) => ot.patch(p)", patch)
                    issues.extend(patch_issues or [])
                except Exception as error:  # noqa: BLE001 - a bad patch is reported, not fatal
                    issues.append(f"patch failed: {type(error).__name__}")
                await page.wait_for_timeout(1000)
            shot = await page.screenshot()
            return bytes(shot), issues
        finally:
            await page.close()
