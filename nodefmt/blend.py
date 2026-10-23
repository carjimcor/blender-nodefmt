# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a layout (layout.Formatter) back to a Blender node tree: node locations, reroutes,
links, and the links of swapped commutative inputs."""

import time

from . import routes
from .ortho import to_px

REROUTE = "NodeReroute"
SLICE = 0.05  # apply_steps: seconds of work between two yields (a modal sort takes Esc in between)


def set_locations(nt, locs, key="location_absolute"):
    """Move the nodes of tree nt to {name: (x, y)} (key: "location_absolute", or "location",
    relative to the parent frame) in one call. Setting a location one node at a time updates the
    tree each time, about a millisecond per node in a large tree; foreach_set does not, and a
    location needs no update (it changes nothing the tree computes): Blender draws the same."""
    if not locs:
        return
    nodes = nt.nodes
    if not nt.is_editable:  # linked from a library (an asset): foreach_set does nothing there
        for n in nodes:
            p = locs.get(n.name)
            if p is not None:
                setattr(n, key, p)
        return
    flat = [0.0] * (2 * len(nodes))
    nodes.foreach_get(key, flat)
    for k, n in enumerate(nodes):
        p = locs.get(n.name)
        if p is not None:
            flat[2 * k], flat[2 * k + 1] = p
    nodes.foreach_set(key, flat)


def pixel_snap(nt, s, part=None):
    """Put every node (of `part`, a set of names, if given) on the pixel grid of UI scale s
    (ortho.py), so its sockets are exactly where the model measures them; moves are under a
    pixel. Reroutes stay: ortho.straighten puts them at a socket's exact height, often off grid."""
    moves = {}
    for n in nt.nodes:
        if n.bl_idname in ("NodeFrame", "NodeReroute") or (part is not None and n.name not in part):
            continue
        x, y = n.location_absolute
        px, py = to_px(x, s), to_px(y, s)
        if abs(px - x) > 1e-5 or abs(py - y) > 1e-5:
            moves[n.name] = (px, py)
    set_locations(nt, moves)


def socket_of(nt, g):
    """The Blender socket of a gid (node name, 'i' | 'o', index)."""
    n = nt.nodes[g[0]]
    socks = n.outputs if g[1] == "o" else n.inputs
    if g[2] >= len(socks):
        raise IndexError(f"{g} not found: node {n.name!r} ({n.bl_idname}) has {len(socks)}")
    return socks[g[2]]


def apply(nt, f):
    """Write layout f (layout.Formatter) to tree nt: node locations, reroutes and links. New
    links are made before old reroutes are removed, so no input is left unlinked on the way
    (some nodes, like the Viewer, drop unlinked items). Returns the number of reroutes made."""
    gen = apply_steps(nt, f)
    while True:
        try:
            next(gen)
        except StopIteration as e:
            return e.value


def apply_steps(nt, f):
    """apply as a generator that yields every SLICE seconds of work (each new reroute or link
    costs milliseconds in a large tree) and returns what apply returns. Closing it early leaves
    the tree half written: restore it from a check.Snapshot."""
    t0 = [time.perf_counter()]

    def due():
        """True once SLICE seconds have passed since the last yield (then counts again)."""
        if time.perf_counter() - t0[0] < SLICE:
            return False
        t0[0] = time.perf_counter()
        return True

    m = f.m
    trees = f.trees
    muted = {(s, d): mu for s, d, mu, _ in f.links}
    order = {}
    for s, d, mu, sid in f.links:
        order.setdefault(d, []).append((sid, s))
    sc = m.data.get("scale", 1.0)  # node locations on the pixel grid of the UI scale (ortho.py)
    set_locations(nt, {name: (to_px(x, sc), to_px(-y, sc)) for name, (x, y) in f.pos.items()})
    names = {n.name for n in nt.nodes}
    nxt = [1]

    def fresh():
        """A reroute name that is not taken yet (the lowest number above the last one given)."""
        while f"Reroute.{nxt[0]:03d}" in names:
            nxt[0] += 1
        names.add(f"Reroute.{nxt[0]:03d}")
        return f"Reroute.{nxt[0]:03d}"

    # a reroute that lies inside a frame belongs to it (the innermost one); only the frame's
    # inner area counts, so a reroute never makes Blender grow the frame around it
    rects = []
    for r in sorted(f._frame_rects(), key=lambda r: r["w"] * r["h"]):
        pl, pt, pr, pb = m.pads.get(r["name"], (30, 40, 30, 30))
        rects.append((r["name"], r["x"] + pl, r["y"] + pt, r["x"] + r["w"] - pr, r["y"] + r["h"] - pb))

    def frame_at(p):
        """The innermost frame whose inner area holds layout point p, or None."""
        for name, x0, y0, x1, y1 in rects:
            if x0 <= p[0] <= x1 and y0 <= p[1] <= y1:
                return nt.nodes.get(name)
        return None

    made = 0
    nodes_of = {}
    at = {}  # reroute name -> location, set in one call once they all exist
    for s, t in trees.items():
        rr = {}
        for p in routes.reroute_points(t):
            if (s, p) in f.label_pts:  # a labelled reroute goes back on its wire
                r = nt.nodes[f.label_pts[(s, p)][0]]
            else:
                r = nt.nodes.new(REROUTE)
                r.name = fresh()
                made += 1
                if due():
                    yield
            frame = frame_at(p)
            if r.parent != frame:  # before the location: it is set as an absolute one below
                r.parent = frame
            at[r.name] = (to_px(p[0], sc), to_px(-p[1], sc))
            rr[p] = r
        nodes_of[s] = rr
    set_locations(nt, at)
    final = {}  # destination socket -> [(source gid, point)]
    for s, t in trees.items():
        rr = nodes_of[s]
        for p, cs in t.children.items():
            if p != t.root and p not in rr:
                continue
            for q in cs:
                if q in t.dst:  # keyed by the real socket (a multi-input slot key has a 4th item)
                    final.setdefault(t.dst[q][:3], []).append((s, p, t.dst[q]))
                else:
                    frm = socket_of(nt, s) if p == t.root else rr[p].outputs[0]
                    if nt.links.new(frm, rr[q].inputs[0]) is None:
                        raise RuntimeError(f"could not link reroutes of {s}")
                    if due():
                        yield

    def from_socket(s, p):
        """The output a link starts from: source socket s itself, or the reroute at point p."""
        return socket_of(nt, s) if p == trees[s].root else nodes_of[s][p].outputs[0]

    for d, srcs in sorted(final.items()):
        to = socket_of(nt, d)
        if to.is_multi_input:
            # relink bottom slot first: Blender gives each new link the next sort id
            rank = {src: k for k, (sid, src) in enumerate(sorted(order[d], key=lambda x: x[0]))}
            for lk in [lk for lk in to.links if not lk.is_hidden]:
                nt.links.remove(lk)
            for s, p, key in sorted(srcs, key=lambda x: x[2][3] if len(x[2]) > 3 else rank.get(x[0], 0)):
                lk = nt.links.new(from_socket(s, p), socket_of(nt, d))
                if lk is None:
                    raise RuntimeError(f"could not link {s} -> {d}")
                lk.is_muted = muted.get((s, d), False)
            if due():
                yield
            continue
        ((s, p, _),) = srcs
        frm = from_socket(s, p)
        old = to.links[0] if to.is_linked else None
        if old is not None and old.from_socket.as_pointer() == frm.as_pointer():
            continue  # unchanged direct link
        lk = nt.links.new(frm, socket_of(nt, d))  # replaces the old link in place
        if lk is None:
            raise RuntimeError(f"could not link {s} -> {d}")
        lk.is_muted = muted.get((s, d), False)
        if due():
            yield
    # the sockets drawn at the same point as a link's end (model.read: twins) get the same source
    for d, others in m.data.get("twins", []):
        srcs = final.get(tuple(d))
        if not srcs:
            continue
        s, p, _ = srcs[0]
        frm = from_socket(s, p)
        for o in others:
            to = socket_of(nt, o)
            old = to.links[0] if to.is_linked else None
            if old is not None and old.from_socket.as_pointer() == frm.as_pointer():
                continue
            lk = nt.links.new(frm, to)
            if lk is None:
                raise RuntimeError(f"could not link {s} -> {o}")
            lk.is_muted = muted.get((s, tuple(d)), False)
    # unlink the inputs that lost their link to a swap
    for _, a, b in f.swapped:
        for g in (a, b):
            if g not in final:
                to = socket_of(nt, g)
                for lk in [lk for lk in to.links if not lk.is_hidden]:
                    nt.links.remove(lk)
    placed = {v[0] for v in f.label_pts.values()}
    for name in m.data["removable"]:
        n = nt.nodes.get(name)
        if n is not None and name not in placed:
            nt.nodes.remove(n)
            if due():
                yield
    return made
