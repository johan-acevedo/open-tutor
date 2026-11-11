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
from .screen_gateway import register_screen_routes

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
    name: str = Field(min_length=1, max_length=40)
    grade: int | None = Field(default=None, ge=1, le=12)
    notes: list[NoteIn] = Field(default_factory=list, max_length=5)


class ScreenCapability(BaseModel):
    version: int = Field(ge=1, le=1)


class SessionRequest(BaseModel):
    learner: Learner
    board: BoardInfo = BoardInfo()
    screen: ScreenCapability | None = None


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
    access_code = env.get("TUTOR_ACCESS_CODE", "")
    allowed_countries = {country.strip().upper() for country in env.get("TUTOR_ALLOWED_COUNTRIES", "").split(",") if country.strip()}

    @app.middleware("http")
    async def country_access(request: Request, call_next):
        # This opt-in restriction requires a private origin reached through Cloudflare.
        # Health remains available for the machine's local service checks.
        if allowed_countries and request.url.path != "/api/health":
            if request.headers.get("cf-ipcountry", "").upper() not in allowed_countries:
                return JSONResponse(status_code=403, content={"detail": "Open Tutor is currently available from Sweden only."})
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "livekit": bool(env.get("LIVEKIT_URL"))}

    register_screen_routes(app, env)

    @app.post("/api/session")
    async def create_session(body: SessionRequest, request: Request) -> dict[str, str]:
        if access_code and not secrets.compare_digest(request.headers.get("x-tutor-code", ""), access_code):
            raise HTTPException(status_code=401, detail="code")
        for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
            if not env.get(name):
                raise HTTPException(status_code=503, detail="not configured")
        if not limiter.allow():
            raise HTTPException(status_code=429, detail="busy")
        room = "tutor-" + secrets.token_urlsafe(9)
        identity = "learner-" + secrets.token_hex(4)
        metadata = json.dumps({"learner": body.learner.model_dump(exclude_none=True),
                               "board": body.board.model_dump(),
                               **({"screen": body.screen.model_dump()} if body.screen else {})}, ensure_ascii=False)
        token = (
            api.AccessToken(env["LIVEKIT_API_KEY"], env["LIVEKIT_API_SECRET"])
            .with_identity(identity)
            .with_name(body.learner.name)
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

    if (WEB_DIST / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        async def page(path: str) -> FileResponse:
            candidate = (WEB_DIST / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
                return FileResponse(candidate)
            return FileResponse(WEB_DIST / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
