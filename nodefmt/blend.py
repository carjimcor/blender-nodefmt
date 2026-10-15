# SPDX-License-Identifier: GPL-3.0-or-later
"""Write a layout (layout.Formatter) back to a Blender node tree: node locations, reroutes,
links, and the links of swapped commutative inputs."""
from . import routes
from .ortho import to_px

REROUTE = 'NodeReroute'


def pixel_snap(nt, s, part=None):
    """Put every node (of `part`, a set of names, if given) on the pixel grid of UI scale s
    (ortho.py), so its sockets are exactly where the model measures them; moves are under a
    pixel. Reroutes stay: ortho.straighten puts them at a socket's exact height, often off grid."""
    for n in nt.nodes:
        if n.bl_idname in ('NodeFrame', 'NodeReroute') or (part is not None and n.name not in part):
            continue
        x, y = n.location_absolute
        px, py = to_px(x, s), to_px(y, s)
        if abs(px - x) > 1e-5 or abs(py - y) > 1e-5:
            n.location_absolute = (px, py)


def socket_of(nt, g):
    """The Blender socket of a gid (node name, 'i' | 'o', index)."""
    n = nt.nodes[g[0]]
    socks = n.outputs if g[1] == 'o' else n.inputs
    if g[2] >= len(socks):
        raise IndexError(f"{g} not found: node {n.name!r} ({n.bl_idname}) has {len(socks)}")
    return socks[g[2]]


def apply(nt, f):
    """Write layout f (layout.Formatter) to tree nt: node locations, reroutes and links. New
    links are made before old reroutes are removed, so no input is left unlinked on the way
    (some nodes, like the Viewer, drop unlinked items). Returns the number of reroutes made."""
    m = f.m
    trees = f.trees
    muted = {(s, d): mu for s, d, mu, _ in f.links}
    order = {}
    for s, d, mu, sid in f.links:
        order.setdefault(d, []).append((sid, s))
    sc = m.data.get("scale", 1.0)  # node locations on the pixel grid of the UI scale (ortho.py)
    for name, (x, y) in f.pos.items():
        nt.nodes[name].location_absolute = (to_px(x, sc), to_px(-y, sc))
    names = {n.name for n in nt.nodes}

    def fresh():
        """A reroute name that is not taken yet."""
        k = 1
        while f"Reroute.{k:03d}" in names:
            k += 1
        names.add(f"Reroute.{k:03d}")
        return f"Reroute.{k:03d}"

    made = 0
    nodes_of = {}
    for s, t in trees.items():
        rr = {}
        for p in routes.reroute_points(t):
            if (s, p) in f.label_pts:  # a labelled reroute goes back on its wire
                r = nt.nodes[f.label_pts[(s, p)][0]]
            else:
                r = nt.nodes.new(REROUTE)
                r.name = fresh()
                made += 1
            r.location_absolute = (to_px(p[0], sc), to_px(-p[1], sc))
            rr[p] = r
        nodes_of[s] = rr
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

    def from_socket(s, p):
        """The output a link starts from: source socket s itself, or the reroute at point p."""
        return socket_of(nt, s) if p == trees[s].root else nodes_of[s][p].outputs[0]

    for d, srcs in sorted(final.items()):
        to = socket_of(nt, d)
        if to.is_multi_input:
            # relink bottom slot first: Blender gives each new link the next sort id
            rank = {src: k for k, (sid, src) in enumerate(sorted(order[d], key=lambda x: x[0]))}
            for l in [l for l in to.links if not l.is_hidden]:
                nt.links.remove(l)
            for s, p, key in sorted(srcs, key=lambda x: x[2][3] if len(x[2]) > 3 else rank.get(x[0], 0)):
                l = nt.links.new(from_socket(s, p), socket_of(nt, d))
                if l is None:
                    raise RuntimeError(f"could not link {s} -> {d}")
                l.is_muted = muted.get((s, d), False)
            continue
        (s, p, _), = srcs
        frm = from_socket(s, p)
        old = to.links[0] if to.is_linked else None
        if old is not None and old.from_socket.as_pointer() == frm.as_pointer():
            continue  # unchanged direct link
        l = nt.links.new(frm, socket_of(nt, d))  # replaces the old link in place
        if l is None:
            raise RuntimeError(f"could not link {s} -> {d}")
        l.is_muted = muted.get((s, d), False)
    # unlink the inputs that lost their link to a swap
    for _, a, b in f.swapped:
        for g in (a, b):
            if g not in final:
                to = socket_of(nt, g)
                for l in [l for l in to.links if not l.is_hidden]:
                    nt.links.remove(l)
    placed = {v[0] for v in f.label_pts.values()}
    for name in m.data["removable"]:
        n = nt.nodes.get(name)
        if n is not None and name not in placed:
            nt.nodes.remove(n)
    return made
