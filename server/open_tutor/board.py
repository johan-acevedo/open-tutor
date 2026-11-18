"""Board items the tutor publishes to the browser. Mirrors docs/protocol.md."""

from __future__ import annotations

import itertools
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class _Item(BaseModel):
    id: str = Field(max_length=40)
    title: str | None = Field(default=None, max_length=120)


class ImageItem(_Item):
    kind: Literal["image"] = "image"
    url: str = Field(max_length=2000)
    alt: str = Field(max_length=300)


class PageItem(_Item):
    """One Smart Screen page: only the body travels (LiveKit RPC payloads are
    limited to about 15 kB); the web app holds the shell and composes the frame."""
    kind: Literal["page"] = "page"
    title: str = Field(max_length=120)
    body: str = Field(max_length=15000)


class PendingItem(_Item):
    """"Ritar…" placeholder. Kept: it is the client's arrival state for a card that
    takes a moment, and the browser still validates it."""
    kind: Literal["pending"] = "pending"
    title: str = Field(max_length=120)
    # Expected frame height so the placeholder has the finished size.
    # Upper bound matches BOARD_MAX in agent.py (the client-reported size clamp).
    height: int | None = Field(default=None, ge=80, le=3840)


class ResourceItem(_Item):
    kind: Literal["resource"] = "resource"
    title: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    embedUrl: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=200)


BoardItem = Annotated[
    Union[
        ImageItem,
        PendingItem,
        ResourceItem,
        PageItem,
    ],
    Field(discriminator="kind"),
]
board_item = TypeAdapter(BoardItem)


class Note(BaseModel):
    at: str
    topic: str = Field(max_length=120)
    clicked: str | None = Field(default=None, max_length=300)
    tricky: str | None = Field(default=None, max_length=300)
    next: str | None = Field(default=None, max_length=300)


class Ids:
    """Short, readable board ids the model can refer back to (b1, b2, …)."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def next(self) -> str:
        return f"b{next(self._counter)}"


def youtube_embed(url: str) -> str | None:
    """An embeddable URL for common YouTube links, else None (open in a new tab)."""
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").removeprefix("www.").removeprefix("m.")
    video = None
    if host == "youtu.be":
        video = parsed.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com"):
        if parsed.path == "/watch":
            video = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            video = parsed.path.split("/")[2]
    if video and video.replace("-", "").replace("_", "").isalnum() and len(video) <= 20:
        return f"https://www.youtube-nocookie.com/embed/{video}?rel=0"
    return None
