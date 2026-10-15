# SPDX-License-Identifier: GPL-3.0-or-later
"""Sort Selection (sort_selection): format only part of a tree, the selected nodes and
reroutes or what is inside a selected frame. Everything else stays where it is.

1. The part: the selected nodes, the nodes inside selected frames, the selected reroutes on
   wires that reach them, and the frames whose nodes are all in the part.
2. Each link to the rest gets a pin, a reroute of the part standing for the outside end; pins
   of incoming links take the first column, outgoing ones the last, so the links to the rest
   leave the block on its left and right edges.
3. The part is laid out like a whole tree (model.read with `part`, layout.Formatter), written
   back with its top-left corner where it was, then moved down or right (the smaller move)
   off any node of the rest.
4. Router draws the links from the pins to the outside sockets, orthogonally.
5. Wires of the part are straightened, the logic is checked, and the selection is restored
   with the new reroutes added.
"""

from itertools import pairwise

from . import blend, check, model, ortho, rules
from . import params as P
from .layout import Formatter

REROUTE = "NodeReroute"
FRAME = "NodeFrame"
GAP = 20.0  # from the block to the first track of its links to the rest
TRACK = 10.0  # between those tracks (and the steps the router tries)
CLEAR_X = 50.0  # the block keeps this far from the nodes of the rest, left and right (room
# for a vertical run of a link between them: GAP + 2 CLEAR_WIRE) ...
CLEAR_Y = 30.0  # ... and above and below
CLEAR_WIRE = 12.0  # a link to the rest keeps this far from nodes (NF032)


class EmptySelection(Exception):
    """Nothing is selected that can be sorted."""


def _descendants(nt, frame):
    """Every node inside frame `frame` (nested frames too)."""
    out = set()
    for n in nt.nodes:
        p = n.parent
        while p is not None:
            if p == frame:
                out.add(n.name)
                break
            p = p.parent
    return out


def _source(link):
    """The node that feeds a link through reroutes (None if dangling)."""
    for _ in range(1000):
        n = link.from_node
        if n.bl_idname != REROUTE:
            return n
        ins = n.inputs[0].links
        if not ins:
            return None
        link = ins[0]
    return None


def _targets(node, depth=0):
    """Real nodes a reroute leads to."""
    out = set()
    if depth > 500:
        return out
    for lk in node.outputs[0].links:
        if lk.to_node.bl_idname == REROUTE:
            out |= _targets(lk.to_node, depth + 1)
        else:
            out.add(lk.to_node)
    return out


def selection(nt):
    """(real nodes, reroutes, frames) of the part to sort, as name sets: see the module
    docstring. The selected frames are part of the part when all their nodes are."""
    real, rr = set(), set()
    for n in nt.nodes:
        if not n.select:
            continue
        if n.bl_idname == FRAME:
            for k in _descendants(nt, n):
                (rr if nt.nodes[k].bl_idname == REROUTE else real).add(k)
        elif n.bl_idname == REROUTE:
            rr.add(n.name)
        else:
            real.add(n.name)
    real = {k for k in real if nt.nodes[k].bl_idname != FRAME}
    keep = set()
    for k in rr:  # a selected reroute on a wire of the rest only is not part of the part
        r = nt.nodes[k]
        src = _source(r.inputs[0].links[0]) if r.inputs[0].links else None
        if (src is not None and src.name in real) or any(t.name in real for t in _targets(r)):
            keep.add(k)
    frames = set()
    for f in nt.nodes:
        if f.bl_idname == FRAME:
            inside = _descendants(nt, f)
            if inside and all(k in real or k in keep or nt.nodes[k].bl_idname == FRAME for k in inside):
                frames.add(f.name)
    return real, keep, frames


def _box(n, ui):
    """(left, bottom, right, top) of a drawn node, y up; a reroute is a point."""
    x, y = n.location_absolute
    if n.bl_idname == REROUTE:
        return x, y, x, y
    return x, y - n.dimensions.y / ui, x + n.dimensions.x / ui, y


def _bbox(nt, names, ui):
    """(left, bottom, right, top) of the nodes `names` (frames excluded)."""
    bs = [_box(nt.nodes[k], ui) for k in names if nt.nodes[k].bl_idname != FRAME]
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def _overlaps(a, b, m=0.0, my=None):
    """True if boxes a and b (left, bottom, right, top) overlap, with margin m (my up and down,
    default m)."""
    my = m if my is None else my
    return a[0] < b[2] + m and b[0] < a[2] + m and a[1] < b[3] + my and b[1] < a[3] + my


class _Links:
    """Links of the tree by socket index (Python references to links and sockets go stale while
    links change)."""

    @staticmethod
    def key(lk):
        """(from node, output index, to node, input index, muted, multi-input sort id)."""
        return (
            lk.from_node.name,
            list(lk.from_node.outputs).index(lk.from_socket),
            lk.to_node.name,
            list(lk.to_node.inputs).index(lk.to_socket),
            lk.is_muted,
            lk.multi_input_sort_id if lk.to_socket.is_multi_input else 0,
        )

    @staticmethod
    def relink(nt, changes):
        """Give links new sources: changes {(to node, input index, from node, output index):
        (new from node, new output index)}. Links into a multi-input socket are made again in
        their order."""
        by_socket = {}
        for lk in nt.links:
            k = _Links.key(lk)
            by_socket.setdefault((k[2], k[3]), []).append(k)
        for (tn, ti), ks in sorted(by_socket.items()):
            if not any((tn, ti, k[0], k[1]) in changes for k in ks):
                continue
            to = nt.nodes[tn].inputs[ti]
            if to.is_multi_input:
                ks.sort(key=lambda k: k[5])
                for lk in list(to.links):
                    nt.links.remove(lk)
                for fn, fi, _, _, muted, _ in ks:
                    fn, fi = changes.get((tn, ti, fn, fi), (fn, fi))
                    lk = nt.links.new(nt.nodes[fn].outputs[fi], nt.nodes[tn].inputs[ti])
                    lk.is_muted = muted
            else:
                fn, fi, _, _, muted, _ = ks[0]
                fn, fi = changes[(tn, ti, fn, fi)]
                lk = nt.links.new(nt.nodes[fn].outputs[fi], nt.nodes[tn].inputs[ti])
                lk.is_muted = muted


def _pins(nt, part):
    """Put a pin on every link between the part and the rest. Returns (pins {name: 'first' |
    'last'}, ins {pin: (outside node, output index)}, outs {pin: [(outside node, input index)]})."""
    groups_in, groups_out = {}, {}
    for lk in nt.links:
        if lk.is_hidden or FRAME in (lk.from_node.bl_idname, lk.to_node.bl_idname):
            continue
        k = _Links.key(lk)
        a, b = k[0] in part, k[2] in part
        if not a and b:
            groups_in.setdefault((k[0], k[1]), []).append(k)
        elif a and not b:
            groups_out.setdefault((k[0], k[1]), []).append(k)
    pins, ins, outs, changes = {}, {}, {}, {}
    for side, groups in (("first", groups_in), ("last", groups_out)):
        for (fn, fi), ks in sorted(groups.items()):
            p = nt.nodes.new(REROUTE)
            src = nt.nodes[fn].outputs[fi]
            near = nt.nodes[ks[0][2]] if side == "first" else nt.nodes[fn]
            p.location_absolute = near.location_absolute
            nt.links.new(src, p.inputs[0])
            pins[p.name] = side
            for k in ks:
                changes[(k[2], k[3], fn, fi)] = (p.name, 0)
            if side == "first":
                ins[p.name] = (fn, fi)
            else:
                outs[p.name] = [(k[2], k[3]) for k in ks]
    _Links.relink(nt, changes)
    return pins, ins, outs


def _reroute(nt, x, y, made):
    """A new reroute at (x, y), recorded in `made`."""
    r = nt.nodes.new(REROUTE)
    r.location_absolute = (x, y)
    made.append(r.name)
    return r


class Router:
    """Orthogonal routes from an output (leaving to the right) to an input socket or reroute
    (arriving from the left): a straight link, a Z (one vertical run in the gap), an L (at a
    reroute end), or a detour (out, up or down, across, back, in). A route keeps CLEAR_WIRE from every node box but its
    own end nodes, and neither runs on another wire's line nor through its points (NF034).
    Boxes and points are y up."""

    def __init__(self, boxes, segments=()):
        """boxes: {node name: (left, bottom, right, top)}; segments: [(wire, p, q)] of the wires
        drawn now (wire: any key, the same for every segment of one wire)."""
        self.boxes = boxes
        self.segments = list(segments)

    def add(self, wire, path):
        """Remember the segments of a new route (a list of points)."""
        self.segments += [(wire, p, q) for p, q in pairwise(path)]

    def _clear(self, p, q, exempt, wire, strict=True, end=None):
        """True if segment p-q passes no box (those in `exempt` only shrunk by 2) and, if
        strict, does not run on, or through a point of, a segment of another wire (but for
        wires that end near point `end`: the other links into one multi-input socket)."""
        x0, x1 = min(p[0], q[0]), max(p[0], q[0])
        y0, y1 = min(p[1], q[1]), max(p[1], q[1])
        for name, b in self.boxes.items():
            m = -2.0 if name in exempt else CLEAR_WIRE
            if x0 < b[2] + m and x1 > b[0] - m and y0 < b[3] + m and y1 > b[1] - m:
                return False
        if not strict:
            return True
        flat = abs(p[1] - q[1]) <= ortho.TOL
        for w, a, b in self.segments:
            if w == wire:
                continue
            if end is not None and min(abs(c[0] - end[0]) + abs(c[1] - end[1]) for c in (a, b)) < 2 * P.RR_CLEAR:
                continue
            if flat and abs(a[1] - b[1]) <= ortho.TOL:  # two horizontal runs on one line
                if abs(a[1] - p[1]) < P.COLLINEAR and min(x1, max(a[0], b[0])) - max(x0, min(a[0], b[0])) > 1.0:
                    return False
            elif (
                not flat
                and abs(a[0] - b[0]) <= ortho.TOL  # two vertical runs
                and abs(a[0] - p[0]) < P.COLLINEAR
                and min(y1, max(a[1], b[1])) - max(y0, min(a[1], b[1])) > 1.0
            ):
                return False
            for c in (a, b):  # through a point of another wire
                if (
                    x0 - P.ON_WIRE < c[0] < x1 + P.ON_WIRE
                    and y0 - P.ON_WIRE < c[1] < y1 + P.ON_WIRE
                    and (c not in (p, q))
                ):
                    return False
        return True

    def route(self, a, b, src, dst, prefer, wire, a_free=False, b_free=False):
        """The corner points of a route from a (on node `src`) to b (on node `dst`) for `wire`:
        [] for a straight link, else the first clear route, preferring a vertical run near x =
        prefer; None if none is clear. a_free (b_free): the end is a reroute, which the wire may
        leave (enter) vertically too."""
        for strict in (True, False):  # clear of other wires if possible, else of nodes only
            pts = self._route(a, b, src, dst, prefer, wire, strict, a_free, b_free)
            if pts is not None:
                return pts
        return None

    def _route(self, a, b, src, dst, prefer, wire, strict, a_free, b_free):
        """route() with or without the checks against other wires."""

        def seg_ok(k, n, p, q):
            """Segment k of n: the first may touch the source node, the last the destination."""
            ex = ({src} if k == 0 else set()) | ({dst} if k == n - 1 else set())
            return self._clear(p, q, ex, wire, strict, b if k == n - 1 else None)

        def ok(pts):
            """True if every segment of a, pts, b is clear (and none has no length)."""
            path = [a] + pts + [b]
            if any(abs(p[0] - q[0]) + abs(p[1] - q[1]) < 1.0 for p, q in pairwise(path)):
                return False
            return all(seg_ok(k, len(path) - 1, p, q) for k, (p, q) in enumerate(pairwise(path)))

        if abs(a[1] - b[1]) <= ortho.TOL and a[0] < b[0] and ok([]):
            return []
        lo, hi = a[0] + GAP, b[0] - GAP
        if lo <= hi:  # a Z: one vertical run in the gap
            xs = sorted(
                {round(lo + TRACK * k, 1) for k in range(int((hi - lo) / TRACK) + 1)} | {hi},
                key=lambda x: (abs(x - prefer), x),
            )
            for x in xs:
                if ok([(x, a[1]), (x, b[1])]):
                    return [(x, a[1]), (x, b[1])]
        if a[0] < b[0]:  # an L: a reroute end may be left or entered vertically
            if a_free and ok([(a[0], b[1])]):
                return [(a[0], b[1])]
            if b_free and ok([(b[0], a[1])]):
                return [(b[0], a[1])]
        # a detour: out to x1, up or down to yd, across to x2, back to b's height, in (a reroute
        # end is left or entered vertically instead)
        ys = set()
        for bx in self.boxes.values():
            ys |= {bx[3] + CLEAR_WIRE + TRACK, bx[1] - CLEAR_WIRE - TRACK}
        mid = (a[1] + b[1]) / 2
        x1s = [a[0] + GAP + TRACK * k for k in range(60)]
        x2s = [b[0] - GAP - TRACK * k for k in range(60)]
        for yd in sorted(ys, key=lambda y: (abs(y - a[1]) + abs(y - b[1]), abs(y - mid))):
            if a_free and b_free and ok([(a[0], yd), (b[0], yd)]):
                return [(a[0], yd), (b[0], yd)]
            if a_free:
                for x2 in x2s:
                    if ok([(a[0], yd), (x2, yd), (x2, b[1])]):
                        return [(a[0], yd), (x2, yd), (x2, b[1])]
            x1 = next((x for x in x1s if seg_ok(0, 5, a, (x, a[1])) and seg_ok(1, 5, (x, a[1]), (x, yd))), None)
            if x1 is None:
                continue
            if b_free and ok([(x1, a[1]), (x1, yd), (b[0], yd)]):
                return [(x1, a[1]), (x1, yd), (b[0], yd)]
            for x2 in x2s:
                pts = [(x1, a[1]), (x1, yd), (x2, yd), (x2, b[1])]
                if ok(pts):
                    return pts
        return None


def _wire_id(sock):
    """The real output socket a wire comes from, through reroutes: (node name, output index)."""
    for _ in range(1000):
        n = sock.node
        if n.bl_idname != REROUTE or not n.inputs[0].links:
            return (n.name, list(n.outputs).index(sock))
        sock = n.inputs[0].links[0].from_socket
    return (sock.node.name, 0)


def _drawn_segments(nt, pins, part):
    """[(wire, p, q)] of every drawn link but the direct links between the pins and the rest
    (they are being replaced)."""

    def temporary(lk):
        """A link between a pin and a node of the rest."""
        a, b = lk.from_node.name, lk.to_node.name
        return (a in pins and b not in part) or (b in pins and a not in part)

    return [(_wire_id(lk.from_socket), a, b) for lk, a, b in ortho.drawn(nt) if not temporary(lk)]


def _wire(nt, router, frm, to_node, to_index, prefer, made, tree):
    """Draw the link from output `frm` to input `to_index` of node `to_node` (may be a reroute)
    on new reroutes along a route of `router`; returns the output to link the input from.
    tree: {point: reroute name} of this wire so far, whose reroutes a route reuses."""
    from .sockets import socket_location

    to = nt.nodes[to_node].inputs[to_index]
    a = socket_location(frm) if frm.node.bl_idname != REROUTE else tuple(frm.node.location_absolute)
    if nt.nodes[to_node].bl_idname == REROUTE:
        b = tuple(nt.nodes[to_node].location_absolute)
    else:
        link = next((lk for lk in to.links if lk.from_node == frm.node), None)
        b = ortho.link_end(link, ortho.slot_gap()) if link is not None else socket_location(to)
    wire = _wire_id(frm)
    pts = router.route(
        a,
        b,
        frm.node.name,
        to_node,
        prefer,
        wire,
        frm.node.bl_idname == REROUTE,
        nt.nodes[to_node].bl_idname == REROUTE,
    )
    if pts is None:  # nothing is clear: a plain Z at the preferred x
        pts = [(prefer, a[1]), (prefer, b[1])] if abs(a[1] - b[1]) > ortho.TOL else []
    router.add(wire, [a] + pts + [b])
    prev = frm
    start = 0
    for k, p in enumerate(pts):  # the part of the route the wire already has
        key = (round(p[0], 1), round(p[1], 1))
        if key not in tree:
            break
        prev = nt.nodes[tree[key]].outputs[0]
        start = k + 1
    for p in pts[start:]:
        r = _reroute(nt, p[0], p[1], made)
        tree[(round(p[0], 1), round(p[1], 1))] = r.name
        nt.links.new(prev, r.inputs[0])
        prev = r.outputs[0]
    return prev


def _socket_y(nt, d):
    """Height of input `d` (node name, input index)."""
    from .sockets import socket_location

    return socket_location(nt.nodes[d[0]].inputs[d[1]])[1]


def _place(nt, names, real, old, ui, others):
    """Move the nodes `names` so that the box of the nodes `real` starts at the top-left of box
    `old` (where they were); then, if the box of `names` overlaps a box of `others`, down or
    right (the smaller move) until it does not. Returns the move made to clear the rest."""
    s = ortho.ui_scale()
    new = _bbox(nt, real, ui)
    dx, dy = ortho.to_px(old[0] - new[0], s), ortho.to_px(old[3] - new[3], s)
    allb = _bbox(nt, names, ui)
    box = (allb[0] + dx, allb[1] + dy, allb[2] + dx, allb[3] + dy)

    def clear(b):
        """The first box of the rest that b overlaps, else None."""
        return next((o for o in others if _overlaps(b, o, CLEAR_X, CLEAR_Y)), None)

    best = (0.0, 0.0)
    if clear(box) is not None:
        found = []
        for axis in (0, 1):  # 0: right, 1: down
            shift = 0.0
            for _ in range(200):
                b = (
                    box[0] + (shift if axis == 0 else 0),
                    box[1] - (shift if axis == 1 else 0),
                    box[2] + (shift if axis == 0 else 0),
                    box[3] - (shift if axis == 1 else 0),
                )
                o = clear(b)
                if o is None:
                    found.append((shift, axis))
                    break
                shift += (o[2] + CLEAR_X - b[0]) if axis == 0 else (b[3] - (o[1] - CLEAR_Y))
        if found:
            shift, axis = min(found)
            shift = ortho.to_px(shift, s)
            best = (shift, 0.0) if axis == 0 else (0.0, -shift)
    for k in names:
        n = nt.nodes[k]
        if n.bl_idname == FRAME:
            continue
        x, y = n.location_absolute
        n.location_absolute = (x + dx + best[0], y + dy + best[1])
    return best


def sort_selection(nt, editor, cfg=None, mode="relayout"):
    """Sort the selected part of tree nt (see the module docstring). On a logic change the tree
    is restored and api.LogicChanged raised. Returns stats."""
    from . import api

    cfg = cfg or rules.Config()
    with rules.applied(cfg):
        return _sort_selection(nt, editor, cfg, mode, api)


def _sort_selection(nt, editor, cfg, mode, api):
    """sort_selection with the layout parameters of cfg set."""
    editor.show(nt)
    real, rr, frames = selection(nt)
    if not real:
        raise EmptySelection("the selection holds no nodes (select nodes, reroutes or a frame)")
    selected = {n.name for n in nt.nodes if n.select}
    before_names = {n.name for n in nt.nodes}
    snap = check.Snapshot(nt)
    before = check.fingerprint(nt)
    ui = ortho.ui_scale()
    try:
        old = _bbox(nt, real, ui)
        part = real | rr | frames
        others = [_box(n, ui) for n in nt.nodes if n.name not in part and n.bl_idname != FRAME]
        others = [b if b[0] < b[2] else (b[0] - 6, b[1] - 6, b[2] + 6, b[3] + 6) for b in others]  # reroutes
        pins, ins, outs = _pins(nt, part)
        part |= set(pins)
        data = api.read_tree(nt, editor, part, pins)
        f = Formatter(model.Model(data), mode, True, rules=cfg.rules).run()
        blend.apply(nt, f)
        editor.redraw()
        laid = [n.name for n in nt.nodes if n.name in part or n.name not in before_names]
        laid = [k for k in laid if nt.nodes[k].bl_idname != FRAME]
        moved = _place(nt, laid, real, old, ui, others)
        editor.redraw()
        box = _bbox(nt, laid, ui)
        placed = _bbox(nt, real, ui)
        made = []
        editor.redraw()
        router = Router(
            {n.name: _box(n, ui) for n in nt.nodes if n.bl_idname not in (FRAME, REROUTE)},
            _drawn_segments(nt, pins, part),
        )
        order = sorted(ins, key=lambda p: -nt.nodes[p].location_absolute[1])
        for k, p in enumerate(order):
            fn, fi = ins[p]
            prev = _wire(nt, router, nt.nodes[fn].outputs[fi], p, 0, box[0] - GAP - TRACK * k, made, {})
            nt.links.new(prev, nt.nodes[p].inputs[0])
        changes = {}
        order = sorted(outs, key=lambda p: -nt.nodes[p].location_absolute[1])
        for k, p in enumerate(order):
            pin, tree = nt.nodes[p], {}
            py = pin.location_absolute[1]
            for tn, ti in sorted(outs[p], key=lambda d: (abs(_socket_y(nt, d) - py), d)):
                prev = _wire(nt, router, pin.outputs[0], tn, ti, box[2] + GAP + TRACK * k, made, tree)
                if prev.node.name != p:
                    changes[(tn, ti, p, 0)] = (prev.node.name, 0)
        _Links.relink(nt, changes)
        new = {n.name for n in nt.nodes if n.name not in before_names}
        movable = (part | new) - frames
        editor.redraw()
        st = ortho.straighten(nt, editor, movable, fan=cfg.on("NF035"))
        if cfg.on("NF034"):
            editor.redraw()
            ortho.drop_straight(nt, movable)
    except Exception as e:
        snap.restore(nt, editor)
        again = check.diff(before, check.fingerprint(nt))
        raise api.LogicChanged(
            f"{api.tree_name(nt)}: sorting the selection failed ({e}), reverted "
            f"({'restore OK' if not again else 'RESTORE FAILED'})"
        ) from e
    d = check.diff(before, check.fingerprint(nt))
    if d:
        snap.restore(nt, editor)
        again = check.diff(before, check.fingerprint(nt))
        raise api.LogicChanged(
            f"{api.tree_name(nt)}: sorting the selection changed the logic, reverted "
            f"({'restore OK' if not again else 'RESTORE FAILED'}): {d[:3]}"
        )
    new = {n.name for n in nt.nodes if n.name not in before_names}
    for n in nt.nodes:
        n.select = n.name in selected or n.name in new
    editor.redraw()
    return {
        "tree": api.tree_name(nt),
        "nodes": len(real),
        "reroutes": len(new),
        "moved": moved,
        "box": placed,
        "old": old,
        "left": st["left"],
    }
