"""Board items the tutor publishes to the browser. Mirrors docs/protocol.md."""

from __future__ import annotations

import itertools
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class Step(BaseModel):
    tex: str = Field(max_length=400)
    note: str | None = Field(default=None, max_length=200)
    op: str | None = Field(default=None, max_length=40)


class _Item(BaseModel):
    id: str = Field(max_length=40)
    title: str | None = Field(default=None, max_length=120)


class TextItem(_Item):
    kind: Literal["text"] = "text"
    markdown: str = Field(max_length=4000)


class StepsItem(_Item):
    kind: Literal["steps"] = "steps"
    steps: list[Step] = Field(min_length=1, max_length=12)


class MindmapItem(_Item):
    kind: Literal["mindmap"] = "mindmap"
    center: str = Field(max_length=80)
    ideas: list[str] = Field(min_length=1, max_length=8)


class SvgItem(_Item):
    kind: Literal["svg"] = "svg"
    svg: str = Field(max_length=60000)


class HtmlItem(_Item):
    kind: Literal["html"] = "html"
    html: str = Field(max_length=100000)
    # The commissioned design size (the visible .ot-board-scroll content box
    # at commission time). The client scales this design box down to fit the
    # current pane, preserving aspect, so fixed-pixel board content always
    # fits without clipping. Upper bounds match BOARD_MAX in agent.py.
    height: int | None = Field(default=None, ge=120, le=3840)
    width: int | None = Field(default=None, ge=120, le=3840)


class ImageItem(_Item):
    kind: Literal["image"] = "image"
    url: str = Field(max_length=2000)
    alt: str = Field(max_length=300)


class PendingItem(_Item):
    kind: Literal["pending"] = "pending"
    title: str = Field(max_length=120)
    # Expected frame height so the placeholder has the finished size.
    # Upper bound matches BOARD_MAX in agent.py (the client-reported size clamp).
    height: int | None = Field(default=None, ge=80, le=3840)


class MaterialItem(_Item):
    kind: Literal["material"] = "material"
    title: str = Field(min_length=1, max_length=200)
    # Stable catalogue section ID only. The browser derives the page URL from
    # this ID; the model can never supply a material URL.
    section_id: str = Field(pattern=r"^sec-[0-9a-f]{16}$")


class ResourceItem(_Item):
    kind: Literal["resource"] = "resource"
    title: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    embedUrl: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=200)


BoardItem = Annotated[
    Union[
        TextItem,
        StepsItem,
        MindmapItem,
        SvgItem,
        HtmlItem,
        ImageItem,
        PendingItem,
        ResourceItem,
        MaterialItem,
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
