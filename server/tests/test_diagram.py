"""Diagram model: stable ids, deterministic layout, atomic changes, and the wire format."""

import json

import pytest
from pydantic import ValidationError

from open_tutor.board import DIAGRAM_MAX_LINKS, DIAGRAM_MAX_NODES, DiagramItem, board_item
from open_tutor.diagram import Diagram, DiagramError, LinkSpec, NodeSpec


def node(id, text, role=None):
    return NodeSpec(id=id, text=text, role=role)


def link(source, target, label=None):
    return LinkSpec(source=source, target=target, label=label)


def overlaps(item):
    boxes = [(n.x, n.y) for n in item.nodes]
    return any(
        abs(ax - bx) < 280 and abs(ay - by) < 130
        for i, (ax, ay) in enumerate(boxes)
        for bx, by in boxes[i + 1 :]
    )


def swedish_map():
    d = Diagram("b1", "Klimat", "radial")
    d.add([node("klimat", "Klimatförändring")], [])
    return d


def test_a_mindmap_grows_without_moving_what_is_already_there():
    d = swedish_map()
    seen = {}
    for i, (nid, text) in enumerate([("vaxt", "Växthusgaser"), ("is", "Smältande is"), ("hav", "Havsnivå"),
                                     ("skog", "Skogsbränder"), ("energi", "Förnybar energi")]):
        d.add([node(nid, text)], [link("klimat", nid)])
        item = d.item()
        assert item.rev == i + 2
        for placed in item.nodes:
            if placed.id in seen:
                assert (placed.x, placed.y) == seen[placed.id], "an existing node moved"
            seen[placed.id] = (placed.x, placed.y)
        assert not overlaps(item)
    assert [n.role for n in d.item().nodes][:2] == ["center", "idea"]
    assert (d.item().nodes[0].x, d.item().nodes[0].y) == (0, 0)


def test_second_level_nodes_sit_outside_their_parent_without_overlap():
    d = swedish_map()
    d.add([node("a", "Orsaker"), node("b", "Följder")], [link("klimat", "a"), link("klimat", "b")])
    d.add([node("a1", "Fossila bränslen"), node("a2", "Skogsavverkning"), node("a3", "Boskap")],
          [link("a", "a1"), link("a", "a2"), link("a", "a3")])
    item = d.item()
    by_id = {n.id: n for n in item.nodes}
    assert not overlaps(item)
    for child in ("a1", "a2", "a3"):
        far = (by_id[child].x ** 2 + by_id[child].y ** 2) ** 0.5
        assert far > (by_id["a"].x ** 2 + by_id["a"].y ** 2) ** 0.5


def test_flow_runs_left_to_right_and_back_arrows_do_not_break_it():
    d = Diagram("b2", "Reaktion", "flow")
    d.add([node("m", "Metan"), node("o", "Syre"), node("r", "Reaktion"), node("c", "Koldioxid"), node("w", "Vatten")],
          [link("m", "r"), link("o", "r"), link("r", "c", "bildas"), link("r", "w")])
    xs = {n.id: n.x for n in d.item().nodes}
    assert xs["m"] == xs["o"] == 0 < xs["r"] < xs["c"] == xs["w"]
    assert {n.role for n in d.item().nodes} == {"step"}
    d.add([], [link("w", "m")])  # a cycle: the arrow is kept, the layers stay finite
    assert len(d.item().links) == 5 and max(n.x for n in d.item().nodes) <= 340 * 5
    assert not overlaps(d.item())


def test_flow_that_cannot_fit_is_refused_and_left_unchanged():
    d = Diagram("b2", None, "flow")
    d.add([node("n0", "0")], [])
    for i in range(1, 6):
        d.add([node(f"n{i}", str(i))], [link(f"n{i-1}", f"n{i}")])
    before, rev = d.item().model_dump(), d.rev
    with pytest.raises(DiagramError, match="too big"):
        d.add([node("n6", "6")], [link("n5", "n6")])
    assert d.item().model_dump() == before and d.rev == rev


def test_edit_changes_only_the_target_and_keeps_position_and_links():
    d = swedish_map()
    d.add([node("a", "Orsak"), node("b", "Följd")], [link("klimat", "a"), link("a", "b", "ger")])
    before = {n.id: (n.x, n.y) for n in d.item().nodes}
    rev = d.rev
    d.edit("a", text="Orsaker till uppvärmning", role="result")
    d.edit("l2", text="leder till")
    item = d.item()
    assert item.rev == rev + 2
    by_id = {n.id: n for n in item.nodes}
    assert by_id["a"].text == "Orsaker till uppvärmning" and by_id["a"].role == "result"
    assert {n.id: (n.x, n.y) for n in item.nodes} == before
    assert [l.label for l in item.links] == [None, "leder till"]
    d.edit("l2", text="")
    assert d.item().links[1].label is None


def test_remove_takes_links_with_it_and_clears_focus():
    d = swedish_map()
    d.add([node("a", "A"), node("b", "B")], [link("klimat", "a"), link("klimat", "b"), link("a", "b")])
    d.set_focus(["a", "l3"])
    d.remove(["a"])
    item = d.item()
    assert [n.id for n in item.nodes] == ["klimat", "b"]
    assert [(l.source, l.target) for l in item.links] == [("klimat", "b")]
    assert item.focus == []
    d.add([node("c", "C")], [link("klimat", "c")])
    assert [l.id for l in d.item().links] == ["l2", "l4"], "link ids are never reused"


@pytest.mark.parametrize(
    "action, message",
    [
        (lambda d: d.add([node("klimat", "Dubbel")], []), "already used"),
        (lambda d: d.add([], [link("klimat", "saknas")]), "no node 'saknas'"),
        (lambda d: d.add([node("x", "X")], [link("x", "x")]), "two different"),
        (lambda d: d.edit("nope", text="x"), "no node or link"),
        (lambda d: d.remove(["klimat", "a"]), "every node"),
        (lambda d: d.set_focus(["nope"]), "no node or link"),
        (lambda d: d.edit("klimat", role="link"), "role"),
    ],
)
def test_bad_changes_are_refused_atomically(action, message):
    d = swedish_map()
    d.add([node("a", "A")], [link("klimat", "a")])
    before, rev = d.item().model_dump(), d.rev
    with pytest.raises((DiagramError, ValidationError)) as error:
        action(d)
    assert message in str(error.value)
    assert d.item().model_dump() == before and d.rev == rev


def test_limits_hold_and_the_largest_diagram_fits_one_rpc():
    d = Diagram("b1", "Stor", "radial")
    d.add([node("n0", "Mitt")], [])
    for i in range(1, DIAGRAM_MAX_NODES):
        d.add([node(f"n{i}", "ö" * 60)], [link(f"n{(i - 1) // 3}", f"n{i}", "å" * 30)])
    assert len(d.item().nodes) == DIAGRAM_MAX_NODES and not overlaps(d.item())
    assert all(abs(n.x) <= 4000 and abs(n.y) <= 4000 for n in d.item().nodes)
    with pytest.raises(DiagramError, match="at most"):
        d.add([node("extra", "För mycket")], [])
    d.set_focus([n.id for n in d.item().nodes][:20] + [l.id for l in d.item().links][:20])
    assert len(d.item().links) <= DIAGRAM_MAX_LINKS
    wire = json.dumps(d.item().model_dump(exclude_none=True), ensure_ascii=False).encode()
    assert len(wire) < 15_000, "LiveKit RPC payloads are limited to 15 KiB"


def test_wire_format_round_trips_through_the_board_union():
    d = swedish_map()
    d.add([node("a", "Växthusgaser")], [link("klimat", "a", "orsakas av")])
    wire = d.item().model_dump(exclude_none=True)
    assert wire["kind"] == "diagram" and wire["rev"] == 2 and wire["layout"] == "radial"
    assert wire["links"] == [{"id": "l1", "source": "klimat", "target": "a", "label": "orsakas av"}]
    assert isinstance(board_item.validate_python(wire), DiagramItem)
    with pytest.raises(ValidationError):
        board_item.validate_python({**wire, "links": [{"id": "l1", "source": "klimat", "target": "ghost"}]})
    with pytest.raises(ValidationError):
        board_item.validate_python({**wire, "nodes": wire["nodes"] + [{**wire["nodes"][0]}]})
