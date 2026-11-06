"""Board items the tutor publishes to the browser. Mirrors docs/protocol.md."""

from __future__ import annotations

import itertools
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter, model_validator


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
    height: int | None = Field(default=None, ge=120, le=900)


class ImageItem(_Item):
    kind: Literal["image"] = "image"
    url: str = Field(max_length=2000)
    alt: str = Field(max_length=300)


class PendingItem(_Item):
    kind: Literal["pending"] = "pending"
    title: str = Field(max_length=120)


class ResourceItem(_Item):
    kind: Literal["resource"] = "resource"
    title: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    embedUrl: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=200)


DIAGRAM_ROLES = ("center", "idea", "step", "result", "note")
DIAGRAM_LAYOUTS = ("radial", "flow")
DiagramRole = Literal["center", "idea", "step", "result", "note"]
DIAGRAM_MAX_NODES = 24
DIAGRAM_MAX_LINKS = 40
DIAGRAM_COORD_LIMIT = 4000  # |x|, |y| of a node centre, in scene units
DIAGRAM_ID = r"^[A-Za-z0-9_-]{1,24}$"


class DiagramNode(BaseModel):
    id: str = Field(pattern=DIAGRAM_ID)
    text: str = Field(min_length=1, max_length=60)
    role: DiagramRole = "idea"
    x: float = Field(ge=-DIAGRAM_COORD_LIMIT, le=DIAGRAM_COORD_LIMIT)  # centre of the node
    y: float = Field(ge=-DIAGRAM_COORD_LIMIT, le=DIAGRAM_COORD_LIMIT)


class DiagramLink(BaseModel):
    id: str = Field(pattern=DIAGRAM_ID)
    source: str = Field(pattern=DIAGRAM_ID)
    target: str = Field(pattern=DIAGRAM_ID)
    label: str | None = Field(default=None, max_length=30)


class DiagramItem(_Item):
    """A connected diagram. The tutor owns the model and sends all of it on every change.

    `rev` rises with every change; the browser acknowledges a revision only once the scene shows it.
    Coordinates are node centres chosen by the server (open_tutor.diagram), never by the model.
    """

    kind: Literal["diagram"] = "diagram"
    rev: int = Field(ge=1)
    layout: Literal["radial", "flow"]
    nodes: list[DiagramNode] = Field(min_length=1, max_length=DIAGRAM_MAX_NODES)
    links: list[DiagramLink] = Field(default_factory=list, max_length=DIAGRAM_MAX_LINKS)
    focus: list[str] = Field(default_factory=list, max_length=DIAGRAM_MAX_NODES + DIAGRAM_MAX_LINKS)

    @model_validator(mode="after")
    def _consistent(self) -> "DiagramItem":
        node_ids = [n.id for n in self.nodes]
        link_ids = [link.id for link in self.links]
        if len(set(node_ids + link_ids)) != len(node_ids) + len(link_ids):
            raise ValueError("node and link ids must be unique")
        known = set(node_ids)
        for link in self.links:
            if link.source not in known or link.target not in known:
                raise ValueError(f"link {link.id} points at a node that does not exist")
        if any(f not in known and f not in set(link_ids) for f in self.focus):
            raise ValueError("focus names an id that does not exist")
        return self


BoardItem = Annotated[
    Union[TextItem, StepsItem, MindmapItem, SvgItem, HtmlItem, ImageItem, PendingItem, ResourceItem, DiagramItem],
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
