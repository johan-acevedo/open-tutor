"""Small web service: serves the built page and issues short-lived room tokens.

Run with `uvicorn open_tutor.web:app --port 8710`.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from collections import deque
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel, Field

from .config import AGENT_NAME
from .analytics import posthog_settings
from .reviewed_images import find_reviewed_image, media_type_for, sessions_base_dir

WEB_DIST = Path(os.environ.get("TUTOR_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
TOKEN_TTL = timedelta(hours=3)


class NoteIn(BaseModel):
    at: str = Field(default="", max_length=40)
    topic: str = Field(default="", max_length=120)
    clicked: str | None = Field(default=None, max_length=300)
    tricky: str | None = Field(default=None, max_length=300)
    next: str | None = Field(default=None, max_length=300)


class BoardInfo(BaseModel):
    w: int = Field(default=1920, ge=320, le=3840)
    h: int = Field(default=1080, ge=320, le=3840)
    device: str = Field(default="desktop", max_length=20)


class Learner(BaseModel):
    # Browser profile id, so the worker's learner RPCs (learner.setName,
    # learner.setGrade) can name their target. Sent by the page, echoed in metadata.
    id: str | None = Field(default=None, max_length=100)
    # Empty on a voice-first start: the call begins with no name and the tutor
    # learns it by voice (set_learner_name) early in the call.
    name: str = Field(default="", max_length=40)
    grade: int | None = Field(default=None, ge=1, le=12)
    notes: list[NoteIn] = Field(default_factory=list, max_length=5)
    # Age band for this page load (primary | middle | upper). Chosen by the
    # request host; validated loosely so older pages keep working.
    band: str | None = Field(default=None, max_length=12)
    # Session language (BCP-47 style, e.g. "sv"). Only Swedish exists for now;
    # the worker falls back to it for anything else. Sent by the page from
    # web/src/locales/sv.ts so later languages need no protocol change.
    locale: str = Field(default="sv", max_length=12)


class SessionRequest(BaseModel):
    learner: Learner
    board: BoardInfo = BoardInfo()
    # Random per-browser id (crypto.randomUUID, localStorage) so sessions from
    # the same device can be counted together. Opaque: never personal data.
    device_id: str | None = Field(default=None, max_length=100)


class SessionLimiter:
    """Owner spending control: a cap on new sessions per hour for the whole instance.

    Family use needs no accounts; this only stops a leaked URL from running up
    provider costs. TUTOR_MAX_SESSIONS_PER_HOUR (default 12) sets the cap.
    """

    def __init__(self, per_hour: int) -> None:
        self.per_hour = per_hour
        self.started: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        while self.started and now - self.started[0] > 3600:
            self.started.popleft()
        if len(self.started) >= self.per_hour:
            return False
        self.started.append(now)
        return True


def create_app(environ: dict[str, str] | None = None) -> FastAPI:
    env = dict(os.environ if environ is None else environ)
    app = FastAPI(title="Open Tutor", docs_url=None, redoc_url=None, openapi_url=None)
    limiter = SessionLimiter(int(env.get("TUTOR_MAX_SESSIONS_PER_HOUR", "12")))
    allowed_countries = {country.strip().upper() for country in env.get("TUTOR_ALLOWED_COUNTRIES", "").split(",") if country.strip()}

    @app.middleware("http")
    async def country_access(request: Request, call_next):
        # This opt-in restriction requires a private origin reached through Cloudflare.
        # Health remains available for the machine's local service checks.
        if allowed_countries and request.url.path != "/api/health":
            if request.headers.get("cf-ipcountry", "").upper() not in allowed_countries:
                return JSONResponse(status_code=403, content={"detail": "Open Tutor is currently available from Sweden only."})
        return await call_next(request)

    @app.get("/api/config")
    async def config() -> dict[str, Any]:
        """Public runtime config for the page. No secrets: only the PostHog
        project token (``phc_…``, meant to be public) and host, or null when
        analytics is off, plus the testing band override (``TUTOR_BAND``) or
        null. Passes through the country middleware like other routes.
        """
        settings = posthog_settings(env)
        band = (env.get("TUTOR_BAND") or "").strip().lower() or None
        if band not in ("primary", "middle", "upper"):
            band = None
        return {"posthog": settings if settings else None, "band": band}

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "livekit": bool(env.get("LIVEKIT_URL"))}

    images_base = sessions_base_dir(env)

    @app.get("/api/images/{name}")
    async def reviewed_image(name: str) -> FileResponse:
        """Serve one vision-reviewed Parallel image by its content hash.

        Only bytes the page pipeline approved are ever stored, under an
        unguessable ``<sha256>.<ext>`` name; anything else answers 404.
        Immutable content: cached for a year, never sniffed as anything else.
        """
        media_type = media_type_for(name)
        path = find_reviewed_image(images_base, name) if media_type else None
        if path is None:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(path, media_type=media_type,
                            headers={"Cache-Control": "public, max-age=31536000, immutable",
                                     "X-Content-Type-Options": "nosniff"})

    @app.post("/api/session")
    async def create_session(body: SessionRequest, request: Request) -> dict[str, str]:
        # No access code: the public instance is open. Protection is the
        # Sweden-only check (middleware above) plus the hourly session cap.
        for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
            if not env.get(name):
                raise HTTPException(status_code=503, detail="not configured")
        if not limiter.allow():
            raise HTTPException(status_code=429, detail="busy")
        room = "tutor-" + secrets.token_urlsafe(9)
        identity = "learner-" + secrets.token_hex(4)
        meta: dict[str, Any] = {"learner": body.learner.model_dump(exclude_none=True),
                                "board": body.board.model_dump()}
        if body.device_id:
            meta["device_id"] = body.device_id
        metadata = json.dumps(meta, ensure_ascii=False)
        token = (
            api.AccessToken(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
            .with_identity(identity)
            .with_name(body.learner.name or "elev")
            .with_metadata(metadata)
            .with_ttl(TOKEN_TTL)
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                                         can_publish_data=True))
            .with_room_config(api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)],
                empty_timeout=60,
                max_participants=3,
            ))
            .to_jwt()
        )
        return {"url": env["LIVEKIT_URL"], "token": token, "room": room}

    # Mounted last: the catch-all page route must not shadow the API routes above.
    if (WEB_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        async def page(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (WEB_DIST / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
