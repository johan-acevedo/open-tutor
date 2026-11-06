"""Authoritative state of the tutor's connected diagrams (mindmaps and flows).

The model never writes scene JSON or coordinates. It names nodes and links with short ids and the
server turns that into a `DiagramItem` (open_tutor.board) with a revision number and a deterministic
layout. Every change sends the whole item, so the browser needs no history and a missed update heals
on the next one. The browser only draws it (web/src/diagram*).
"""

from __future__ import annotations

import copy
import math
from typing import Callable

from pydantic import BaseModel, Field

from .board import (
    DIAGRAM_COORD_LIMIT,
    DIAGRAM_ID,
    DIAGRAM_MAX_LINKS,
    DIAGRAM_MAX_NODES,
    DiagramItem,
    DiagramLink,
    DiagramNode,
    DiagramRole,
)


class DiagramError(ValueError):
    """The change cannot be applied; the message is written for the tutor model to act on."""


class NodeSpec(BaseModel):
    id: str = Field(pattern=DIAGRAM_ID, description="Short id you choose, e.g. 'klimat'. Unique in the diagram.")
    text: str = Field(min_length=1, max_length=60, description="Short Swedish label, a few words.")
    role: DiagramRole | None = Field(
        default=None,
        description="center (the main subject), idea, step, result (an outcome or answer) or note. Optional.",
    )


class LinkSpec(BaseModel):
    source: str = Field(pattern=DIAGRAM_ID, description="Id of the node the arrow starts at.")
    target: str = Field(pattern=DIAGRAM_ID, description="Id of the node the arrow points to.")
    label: str | None = Field(default=None, max_length=30, description="Optional very short label on the arrow.")


# Node boxes are at most about 255 x 110 scene units once the browser has wrapped the text, so two
# centres closer than this overlap.
SPACING_X = 280
SPACING_Y = 130
ROOT_RX, ROOT_RY = 400, 230
FLOW_DX, FLOW_DY = 340, 150
FLOW_MAX_LAYERS, FLOW_MAX_ROWS = 6, 5
SLOT_ANGLES = (0, 180, 270, 90, 315, 225, 45, 135, 22, 202, 292, 112, 338, 158, 248, 68)


def _free(x: float, y: float, taken: list[tuple[float, float]]) -> bool:
    return all(abs(x - tx) >= SPACING_X or abs(y - ty) >= SPACING_Y for tx, ty in taken)


def _inside(x: float, y: float) -> bool:
    limit = DIAGRAM_COORD_LIMIT - 200
    return abs(x) <= limit and abs(y) <= limit


def _radial_position(parent: tuple[float, float] | None, root: tuple[float, float], taken) -> tuple[float, float]:
    """A free spot near its parent. Nodes already on the board never move."""
    candidates: list[tuple[float, float]] = []
    if parent is None or parent == root:
        for scale in (1.0, 1.4):
            for angle in SLOT_ANGLES:
                a = math.radians(angle)
                candidates.append((root[0] + ROOT_RX * scale * math.cos(a), root[1] + ROOT_RY * scale * math.sin(a)))
    else:
        outward = math.atan2(parent[1] - root[1], parent[0] - root[0])
        for distance in (300, 390):
            for turn in (0, 30, -30, 60, -60, 90, -90):
                a = outward + math.radians(turn)
                candidates.append((parent[0] + distance * math.cos(a), parent[1] + distance * 0.8 * math.sin(a)))
    for x, y in candidates:
        x, y = round(x), round(y)
        if _inside(x, y) and _free(x, y, taken):
            return float(x), float(y)
    # Crowded: the nearest free grid cell.
    anchor = parent or root
    cells = sorted(
        ((anchor[0] + i * 300, anchor[1] + j * 140) for i in range(-10, 11) for j in range(-10, 11)),
        key=lambda c: (c[0] - anchor[0]) ** 2 + (c[1] - anchor[1]) ** 2,
    )
    for x, y in cells:
        if _inside(x, y) and _free(x, y, taken):
            return float(x), float(y)
    raise DiagramError("There is no room left in this diagram. Remove something or start a new diagram.")


def _flow_positions(order: list[str], links: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    """Left to right by longest path; rows in the order the nodes were added. Back arrows loop back."""
    out: dict[str, list[str]] = {n: [] for n in order}
    indegree = {n: 0 for n in order}
    for source, target in links:
        out[source].append(target)
        indegree[target] += 1
    state: dict[str, int] = {}
    finished: list[str] = []
    forward: list[tuple[str, str]] = []

    def visit(node: str) -> None:
        state[node] = 1
        for nxt in out[node]:
            if state.get(nxt) == 1:
                continue  # back edge: draw it, but it does not create a layer
            forward.append((node, nxt))
            if nxt not in state:
                visit(nxt)
        state[node] = 2
        finished.append(node)

    for node in [n for n in order if indegree[n] == 0] + order:
        if node not in state:
            visit(node)
    layer = {n: 0 for n in order}
    for node in reversed(finished):
        for source, target in forward:
            if source == node:
                layer[target] = max(layer[target], layer[source] + 1)
    rows: dict[int, int] = {}
    positions: dict[str, tuple[float, float]] = {}
    for node in order:
        row = rows.get(layer[node], 0)
        rows[layer[node]] = row + 1
        if layer[node] >= FLOW_MAX_LAYERS or row >= FLOW_MAX_ROWS:
            raise DiagramError(
                f"The flow is too big for the board (at most {FLOW_MAX_LAYERS} steps across and "
                f"{FLOW_MAX_ROWS} rows). Split it into two diagrams."
            )
        positions[node] = (float(layer[node] * FLOW_DX), float(row * FLOW_DY))
    return positions


class Diagram:
    def __init__(self, id: str, title: str | None, layout: str) -> None:
        self.id = id
        self.title = title
        self.layout = layout
        self.nodes: dict[str, DiagramNode] = {}
        self.links: dict[str, DiagramLink] = {}
        self.focus: list[str] = []
        self.rev = 0
        self.shown = False  # the browser has acknowledged some revision of this diagram
        self._link_seq = 0

    # ---- changes ------------------------------------------------------------------------

    def _transaction(self, change: Callable[[], None]) -> None:
        saved = copy.deepcopy((self.nodes, self.links, self.focus, self._link_seq))
        try:
            change()
            DiagramItem(**self._item_fields(self.rev + 1))  # validates the result as a whole
        except Exception:
            self.nodes, self.links, self.focus, self._link_seq = saved
            raise
        self.rev += 1

    def add(self, nodes: list[NodeSpec], links: list[LinkSpec]) -> list[str]:
        """Add nodes and links. Returns the ids given to the new links, in order."""
        new_links: list[str] = []

        def change() -> None:
            if len(self.nodes) + len(nodes) > DIAGRAM_MAX_NODES:
                raise DiagramError(f"A diagram holds at most {DIAGRAM_MAX_NODES} nodes. Remove some or start a new one.")
            if len(self.links) + len(links) > DIAGRAM_MAX_LINKS:
                raise DiagramError(f"A diagram holds at most {DIAGRAM_MAX_LINKS} links.")
            for spec in nodes:
                if spec.id in self.nodes or spec.id in self.links:
                    raise DiagramError(f"The id '{spec.id}' is already used in this diagram. Choose another.")
                self.nodes[spec.id] = DiagramNode(
                    id=spec.id, text=spec.text, role=spec.role or self._default_role(), x=0, y=0
                )
            for spec in links:
                for end in (spec.source, spec.target):
                    if end not in self.nodes:
                        raise DiagramError(f"Link {spec.source}->{spec.target}: there is no node '{end}'.")
                if spec.source == spec.target:
                    raise DiagramError("A link must join two different nodes.")
                if any(l.source == spec.source and l.target == spec.target for l in self.links.values()):
                    raise DiagramError(f"There is already a link {spec.source}->{spec.target}.")
                self._link_seq += 1
                link_id = f"l{self._link_seq}"
                self.links[link_id] = DiagramLink(id=link_id, source=spec.source, target=spec.target, label=spec.label)
                new_links.append(link_id)
            self._place([spec.id for spec in nodes])

        self._transaction(change)
        return new_links

    def _default_role(self) -> DiagramRole:
        if self.layout == "flow":
            return "step"
        return "idea" if self.nodes else "center"

    def edit(self, target: str, text: str | None = None, role: DiagramRole | None = None) -> None:
        def change() -> None:
            if target in self.nodes:
                node = self.nodes[target]
                self.nodes[target] = node.model_copy(
                    update={"text": text if text else node.text, "role": role or node.role}
                )
                DiagramNode.model_validate(self.nodes[target].model_dump())
            elif target in self.links:
                if role:
                    raise DiagramError("A link has no role; change its label with `text` (empty text removes it).")
                if text is not None:
                    label = text.strip() or None
                    link = self.links[target].model_copy(update={"label": label})
                    DiagramLink.model_validate(link.model_dump())
                    self.links[target] = link
            else:
                raise DiagramError(f"There is no node or link '{target}'. Ids: {self.ids()}")

        self._transaction(change)

    def remove(self, ids: list[str]) -> None:
        """Remove nodes (and every link on them) and links."""

        def change() -> None:
            unknown = [i for i in ids if i not in self.nodes and i not in self.links]
            if unknown:
                raise DiagramError(f"There is no node or link {', '.join(unknown)}. Ids: {self.ids()}")
            for i in ids:
                self.nodes.pop(i, None)
                self.links.pop(i, None)
            self.links = {k: l for k, l in self.links.items() if l.source in self.nodes and l.target in self.nodes}
            self.focus = [f for f in self.focus if f in self.nodes or f in self.links]
            if not self.nodes:
                raise DiagramError("That would remove every node. Start a new diagram instead.")
            self._place([])

        self._transaction(change)

    def set_focus(self, ids: list[str]) -> None:
        def change() -> None:
            unknown = [i for i in ids if i not in self.nodes and i not in self.links]
            if unknown:
                raise DiagramError(f"There is no node or link {', '.join(unknown)}. Ids: {self.ids()}")
            self.focus = list(dict.fromkeys(ids))

        self._transaction(change)

    # ---- layout -------------------------------------------------------------------------

    def _place(self, new_ids: list[str]) -> None:
        if self.layout == "flow":
            order = list(self.nodes)
            positions = _flow_positions(order, [(l.source, l.target) for l in self.links.values()])
            for node_id, (x, y) in positions.items():
                self.nodes[node_id] = self.nodes[node_id].model_copy(update={"x": x, "y": y})
            return
        placed = {i: n for i, n in self.nodes.items() if i not in new_ids}
        first = next(iter(self.nodes))
        for node_id in new_ids:
            if not placed:
                position = (0.0, 0.0)
            else:
                root = (placed[first].x, placed[first].y) if first in placed else (0.0, 0.0)
                parent = self._parent_position(node_id, placed)
                position = _radial_position(parent, root, [(n.x, n.y) for n in placed.values()])
            self.nodes[node_id] = self.nodes[node_id].model_copy(update={"x": position[0], "y": position[1]})
            placed[node_id] = self.nodes[node_id]

    def _parent_position(self, node_id: str, placed: dict[str, DiagramNode]) -> tuple[float, float] | None:
        for link in self.links.values():
            if link.target == node_id and link.source in placed:
                return placed[link.source].x, placed[link.source].y
        for link in self.links.values():
            if link.source == node_id and link.target in placed:
                return placed[link.target].x, placed[link.target].y
        return None

    # ---- output -------------------------------------------------------------------------

    def ids(self) -> str:
        return f"nodes {', '.join(self.nodes)}; links {', '.join(self.links) or 'none'}"

    def _item_fields(self, rev: int) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "rev": rev,
            "layout": self.layout,
            "nodes": [n.model_dump() for n in self.nodes.values()],
            "links": [l.model_dump(exclude_none=True) for l in self.links.values()],
            "focus": list(self.focus),
        }

    def item(self) -> DiagramItem:
        return DiagramItem(**self._item_fields(self.rev))

    def describe(self) -> str:
        nodes = "; ".join(f"{n.id}={n.text}" for n in self.nodes.values())
        links = "; ".join(f"{l.id}={l.source}->{l.target}" for l in self.links.values()) or "none"
        return f"Nodes: {nodes}. Links: {links}."
