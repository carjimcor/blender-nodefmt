# SPDX-License-Identifier: GPL-3.0-or-later
"""Exactly orthogonal wires, as Blender draws them.

Blender draws a node at its location rounded to whole pixels (location times UI scale) and its
sockets whole pixels from that corner; a reroute dot sits exactly at its location. At UI scale 1
a pixel is a node unit. At a fractional scale (1.25, 1.5, ...) the socket offsets in units change
with the scale, so a layout made at one scale is a few units off at another. The formatter
therefore lays a tree out at the session's UI scale, puts nodes on its pixel grid (`to_px`), and
finishes with `straighten`, which reads back what Blender drew and fixes what rounding left:

1. reroutes take the exact height (x) of the socket their horizontal (vertical) wire runs to;
   reroutes joined by such a wire share it;
2. a straight link between two sockets that is a little off moves its destination node (or its
   source) onto the other socket's line;
3. what is still off gets an extra bend: two reroutes, so the change of height is vertical.

A drawn segment is orthogonal when |dx| <= TOL or |dy| <= TOL. With NF035 (fan=True), the last
stretch of a link from a reroute into a multi-input socket may be diagonal: it is never mended,
and its reroute keeps the height of the wire into it, not the slot's (`fanned`).
"""
import math

import bpy

from .sockets import socket_location

TOL = 0.5        # a segment is horizontal (vertical) if its ends differ by at most this in y (x)
NUDGE = 4.0      # the largest move of a node that `straighten` makes (rounding, not layout)
MOVES = 3        # straighten: moves of one node at most (no endless back and forth)
ROUNDS = 10      # straighten: rounds of read back and fix
DEBUG = False    # tests: print what straighten finds and does
REROUTE = 'NodeReroute'


def ui_scale():
    """Blender's UI scale factor (resolution scale times the display's DPI factor)."""
    return bpy.context.preferences.system.ui_scale


def slot_gap(s=None):
    """Distance in node units between the links of a multi-input socket: Blender's
    NODE_MULTI_INPUT_LINK_GAP, a quarter of the widget unit (20 pixels at scale 1)."""
    sp = bpy.context.preferences.system
    s = sp.ui_scale if s is None else s
    widget = math.floor(18.0 * s + 0.5) + 2 * round(sp.pixel_size)
    return 0.25 * widget / s


def to_px(v, s):
    """v (node units) rounded to the pixel grid of UI scale s, as a location Blender keeps exactly."""
    return math.floor(v * s + 0.5 + 1e-6) / s


def link_end(l, gap):
    """Where a drawn link meets its input socket: links into a multi-input socket are spread `gap`
    units apart around the socket centre, the highest sort id on top (y up)."""
    x, y = socket_location(l.to_socket)
    s = l.to_socket
    if s.is_multi_input and not l.to_node.hide:
        ids = sorted(k.multi_input_sort_id for k in s.links)
        if len(ids) > 1:
            y = y - (len(ids) - 1) * gap / 2 + ids.index(l.multi_input_sort_id) * gap
    return x, y


def drawn(nt, gap=None):
    """Every drawn link as (link, start, end) in node units, y up."""
    gap = slot_gap() if gap is None else gap
    return [(l, socket_location(l.from_socket), link_end(l, gap)) for l in nt.links
            if not l.is_hidden and l.to_node.bl_idname != 'NodeFrame' and l.from_node.bl_idname != 'NodeFrame']


def bad(a, b):
    """True if the segment a-b is neither horizontal nor vertical (beyond TOL)."""
    return abs(a[0] - b[0]) > TOL + 1e-4 and abs(a[1] - b[1]) > TOL + 1e-4


def fanned(l, a, b):
    """True if drawn link l (from a to b) may be a fan stretch (NF035): from a reroute on the
    left into a multi-input socket of an open node."""
    s = l.to_socket
    return (s.is_multi_input and not l.to_node.hide and l.from_node.bl_idname == REROUTE
            and a[0] < b[0] - TOL)


def faults(nt, gap=None, fan=False):
    """The drawn links that are not exactly horizontal or vertical: [(link, start, end)]. With
    fan (NF035), the stretches of fans into multi-input sockets are not faults."""
    return [(l, a, b) for l, a, b in drawn(nt, gap) if bad(a, b) and not (fan and fanned(l, a, b))]


def count(nt):
    """Number of drawn link segments that are not horizontal or vertical (call after a redraw)."""
    return len(faults(nt))


def straighten(nt, editor, movable=None, fan=False):
    """Make every drawn link segment of `nt` horizontal or vertical (see the module docstring).
    movable (node names): only these nodes and reroutes move, and only links touching them are
    mended (Sort Selection). fan: NF035 is on (fan stretches stay). Returns stats: reroutes
    snapped, nodes nudged, bends added, segments left."""
    s = ui_scale()
    gap = slot_gap(s)
    st = {"snapped": 0, "nudged": 0, "bends": 0, "left": 0}
    moves = {}
    mine = (lambda l: True) if movable is None else (
        lambda l: l.from_node.name in movable or l.to_node.name in movable)
    for k in range(ROUNDS):
        editor.redraw()
        if _snap_reroutes(nt, drawn(nt, gap), st, movable, fan):
            editor.redraw()
        segs = [x for x in drawn(nt, gap) if mine(x[0])]
        if fan:
            segs = [(l, a, b) for l, a, b in segs if not fanned(l, a, b)]
        left = [(l, a, b) for l, a, b in segs if bad(a, b)]
        if DEBUG:
            print(f"straighten {nt.name} round {k}: {len(left)} off", [
                (l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name,
                 [round(v, 3) for v in a], [round(v, 3) for v in b]) for l, a, b in left], flush=True)
        if not left:
            break
        if k < ROUNDS - 2 and _nudge(nt, segs, moves, s, st, movable):
            continue
        _bend(nt, left, s, st)
    editor.redraw()
    st["left"] = sum(1 for l, _, _ in faults(nt, gap, fan) if mine(l))
    return st


def _axis(a, b):
    """'h' if segment a-b is meant to be horizontal (it changes less in y than in x), else 'v'."""
    return 'h' if abs(b[1] - a[1]) <= abs(b[0] - a[0]) else 'v'


def _snap_reroutes(nt, segs, st, movable=None, fan=False):
    """Give reroutes joined by horizontal (vertical) wires one height (x): that of the socket the
    wire runs to, the source socket first. Only reroutes in `movable` move (default all; a fixed
    one counts as a socket). With fan (NF035), a fan stretch does not pull its reroute to the
    slot. Returns the number moved."""
    rr = {n.name: n for n in nt.nodes if n.bl_idname == REROUTE and (movable is None or n.name in movable)}
    parent = {}

    def find(k):
        """Union-find root of key k."""
        while parent.setdefault(k, k) != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    anchors = {}
    for l, a, b in segs:
        if fan and fanned(l, a, b) and abs(a[1] - b[1]) > 2 * TOL:
            continue
        ax = _axis(a, b)
        c = 1 if ax == 'h' else 0
        fa, tb = l.from_node.name, l.to_node.name
        if fa in rr and tb in rr:
            ra, rb = find((ax, fa)), find((ax, tb))
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        elif fa in rr:
            anchors.setdefault((ax, fa), []).append((1, b[c]))   # an input socket
        elif tb in rr:
            anchors.setdefault((ax, tb), []).append((0, a[c]))   # the source socket comes first
    for name in rr:
        for ax in ('h', 'v'):
            find((ax, name))
    groups = {}
    for k in list(parent):
        groups.setdefault(find(k), []).append(k)
    moved = 0
    for root, members in sorted(groups.items()):
        ax = root[0]
        c = 1 if ax == 'h' else 0
        found = sorted(v for m in members for v in anchors.get(m, []))
        if found:
            best = [v for p, v in found if p == found[0][0]]
            target = (min(best) + max(best)) / 2
        else:
            cur = sorted(rr[m[1]].location_absolute[c] for m in members)
            target = cur[len(cur) // 2]
        for _, name in sorted(members):
            r = rr[name]
            loc = list(r.location_absolute)
            if abs(loc[c] - target) > 1e-4:
                loc[c] = target
                r.location_absolute = loc
                moved += 1
    st["snapped"] += moved
    return moved


def _nudge(nt, segs, moves, s, st, movable=None):
    """Move nodes onto the lines of straight links that are a little off: the destination node,
    else the source, by at most NUDGE, each node at most MOVES times in all and once per round.
    Links go left to right and count the moves made this round, so a chain of straight links
    lines up in one round. Returns True if anything moved."""
    shift = {}  # node name -> (dx, dy) of its move in this round
    for l, a, b in sorted(segs, key=lambda x: (x[2][0], x[1][0], x[0].to_node.name, x[0].from_node.name)):
        fa, tb = l.from_node, l.to_node
        if tb.bl_idname == REROUTE:
            continue  # _snap_reroutes lines reroutes up
        c = 1 if _axis(a, b) == 'h' else 0
        delta = (a[c] + shift.get(fa.name, (0.0, 0.0))[c]) - (b[c] + shift.get(tb.name, (0.0, 0.0))[c])
        if abs(delta) <= TOL or abs(delta) > NUDGE:
            continue
        for node, sign in ((tb, 1.0), (fa, -1.0)):
            if node.bl_idname in ('NodeFrame', REROUTE) or node.name in shift or moves.get(node.name, 0) >= MOVES:
                continue
            if movable is not None and node.name not in movable:
                continue  # a node outside the part holds its line: the other end moves
            loc = list(node.location_absolute)
            new = to_px(loc[c] + sign * delta, s)
            d = [0.0, 0.0]
            d[c] = new - loc[c]
            loc[c] = new
            node.location_absolute = loc
            moves[node.name] = moves.get(node.name, 0) + 1
            shift[node.name] = tuple(d)
            st["nudged"] += 1
            break
    return bool(shift)


def _bend(nt, left, s, st):
    """Give each link that is still off two reroutes, so its change of height (or x) is vertical
    (horizontal). A link into a multi-input socket is left as it is (its order would change)."""
    names = {n.name for n in nt.nodes}

    def fresh():
        """A reroute name that is not taken yet."""
        k = 1
        while f"Reroute.{k:03d}" in names:
            k += 1
        names.add(f"Reroute.{k:03d}")
        return f"Reroute.{k:03d}"

    # sockets by index, looked up per link: Python references go stale as links change
    todo = [(l.from_node.name, list(l.from_node.outputs).index(l.from_socket), l.to_node.name,
             list(l.to_node.inputs).index(l.to_socket), l.is_muted, a, b)
            for l, a, b in left if not l.to_socket.is_multi_input]
    for fn, fi, tn, ti, muted, a, b in todo:
        frm, to = nt.nodes[fn].outputs[fi], nt.nodes[tn].inputs[ti]
        if _axis(a, b) == 'h':
            m = to_px((a[0] + b[0]) / 2, s)
            p1, p2 = (m, a[1]), (m, b[1])
        else:
            m = (a[1] + b[1]) / 2
            p1, p2 = (a[0], m), (b[0], m)
        r1, r2 = nt.nodes.new(REROUTE), nt.nodes.new(REROUTE)
        r1.name, r2.name = fresh(), fresh()
        r1.location_absolute, r2.location_absolute = p1, p2
        nt.links.new(frm, r1.inputs[0])
        nt.links.new(r1.outputs[0], r2.inputs[0])
        new = nt.links.new(r2.outputs[0], to)  # replaces the old link
        if new is not None:
            new.is_muted = muted
        st["bends"] += 1


def drop_straight(nt, movable=None):
    """Remove unlabelled reroutes in the middle of a straight run (NF034), which rounding can
    leave after straighten. Links into multi-input sockets are left alone (their order would
    change). movable: only these reroutes (default all). Returns the number removed."""
    gap = slot_gap()
    out = 0
    for r in [n for n in nt.nodes if n.bl_idname == REROUTE and not n.label
              and (movable is None or n.name in movable)]:
        ins, outs = r.inputs[0].links, r.outputs[0].links
        if len(ins) != 1 or len(outs) != 1 or outs[0].to_socket.is_multi_input:
            continue
        a, b, p = socket_location(ins[0].from_socket), link_end(outs[0], gap), tuple(r.location_absolute)
        flat = abs(a[1] - p[1]) <= TOL and abs(b[1] - p[1]) <= TOL and min(a[0], b[0]) < p[0] < max(a[0], b[0])
        tall = abs(a[0] - p[0]) <= TOL and abs(b[0] - p[0]) <= TOL and min(a[1], b[1]) < p[1] < max(a[1], b[1])
        if not (flat or tall):
            continue
        frm, to, muted = ins[0].from_socket, outs[0].to_socket, ins[0].is_muted or outs[0].is_muted
        new = nt.links.new(frm, to)
        if new is None:
            continue
        new.is_muted = muted
        nt.nodes.remove(r)
        out += 1
    return out
