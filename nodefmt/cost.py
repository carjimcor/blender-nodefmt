# SPDX-License-Identifier: GPL-3.0-or-later
"""Layout cost: one number for the quality of a laid out container (lower is better).

The cost is a weighted sum of faults of the routed wires (weights W_* in params.py):

- crossings: a clean crossing (a horizontal and a vertical wire, away from bends and sockets)
  is cheap, as in a hand-made layout where a straight wire crosses a bus at 90 degrees; a
  crossing near a bend, a reroute or a socket, or of a diagonal wire, costs much more; so does
  any crossing inside a bundle (two wires that leave the same node or enter the same node);
- collinear wires (two wires on one line, or right next to each other);
- reroute faults: two bends of different wires at (nearly) one point, or a bend lying on another
  wire (both look like a junction);
- bends (each costs two reroutes), small jogs, vertical run, the drop of a source node's wire,
  height and width.
"""
from . import params as P
from .graph import slot_of


def _near(p, q, d):
    """True if p and q are closer than d along both axes."""
    return abs(p[0] - q[0]) < d and abs(p[1] - q[1]) < d


class CostMixin:
    """Routes and the weighted faults of a layout."""

    def _route(self, detail=False):
        """Route segments of the current placement, as (tag, (x1, y1), (x2, y2)). Every link that
        is not straight turns on its track in the gap after its source column (see
        LayoutBase._turn_y).

        With detail=True each segment is (tag, p, q, edge, p_kind, q_kind), where a kind is
        'sock' (a node socket), 'bend' (a corner, i.e. a reroute) or 'lane' (a point on a lane)."""
        xl = self.col_x[0] - P.COL_GAP / 2
        xr = self.col_x[self.R] + self.colw[self.R] + P.COL_GAP / 2
        segs = []
        for e in self.edges:
            if e.u.kind == 'pin_in':
                p, pk = (xl, e.u.y), 'lane'
            elif e.u.is_point:
                p, pk = (e.u.x, e.u.y), 'lane'
            else:
                dx, dy = e.u.outs.get(e.uk, (e.u.w, 0))
                p, pk = (e.u.x + dx, e.u.y + dy), 'sock'
            if e.v.kind == 'pin_out':
                q, qk = (xr, e.v.y), 'lane'
            elif e.v.is_point:
                q, qk = (e.v.x, e.v.y), 'lane'
            else:
                dx, dy = e.v.ins.get(e.vk, (0, 0))
                q, qk = (e.v.x + dx, e.v.y + dy), 'sock'
            t = self._turn_y(e)
            if t is not None:
                xc = self.track_x[e.u.rank][e.tag]
                a, b = (xc, p[1]), (xc, t)
                if detail:
                    segs += [(e.tag, p, a, e, pk, 'bend'), (e.tag, a, b, e, 'bend', 'bend'),
                             (e.tag, b, q, e, 'bend', qk)]
                else:
                    segs += [(e.tag, p, a), (e.tag, a, b), (e.tag, b, q)]
            else:
                segs.append((e.tag, p, q, e, pk, qk) if detail else (e.tag, p, q))
        return segs

    def _on_border(self, route):
        """NF032 in a zone: horizontal runs on the top or bottom line of the outline Blender draws
        around the zone (its nodes padded by a widget unit; the zone input and output nodes are
        not padded up or down), where a wire looks like part of the border."""
        if self._zone_input() is None:
            return 0
        reals = [i for i in self.items if not i.is_point]
        inner = [i for i in reals if not i.pin]
        if not inner:
            return 0
        pins = [i for i in reals if i.pin]
        top = min([i.y - 20.0 for i in inner] + [i.y for i in pins])
        bottom = max([i.y + i.h + 20.0 for i in inner] + [i.y + i.h for i in pins])
        n = 0
        for _, p, q in route:
            if abs(p[1] - q[1]) <= P.EPS and abs(p[0] - q[0]) > P.CLEAR_RUN:
                if abs(p[1] - top) < P.CLEAR_OUTLINE or abs(p[1] - bottom) < P.CLEAR_OUTLINE:
                    n += 1
        return n

    def _dest_nodes(self, item):
        """Real items a point (dummy, port) or node leads to; used to find bundles."""
        memo = self.__dict__.setdefault('_dest_memo', {})
        if item in memo:
            return memo[item]
        if not item.is_point or item.kind in ('pin_out', 'label'):
            res = frozenset([item.id])
        else:
            memo[item] = frozenset()
            res = frozenset().union(*[self._dest_nodes(f.v) for f in self.succ_edges[item]])
        memo[item] = res
        return res

    def faults(self):
        """Counts of the wire faults of the current layout (see the module docstring)."""
        segs = self._route(detail=True)
        hs, vs, ds = [], [], []
        bends = {}  # point -> tags bending there
        multi = {}  # point -> multi-input sockets whose slot links bend there
        for s in segs:
            tag, p, q, e, pk, qk = s
            for pt, k in ((p, pk), (q, qk)):
                if k == 'bend':
                    key = (round(pt[0], 1), round(pt[1], 1))
                    bends.setdefault(key, set()).add(tag)
                    if _multi(s) is not None:
                        multi.setdefault(key, set()).add(_multi(s))
            if abs(p[1] - q[1]) <= P.EPS:
                if abs(p[0] - q[0]) > P.EPS:
                    hs.append(s)
            elif abs(p[0] - q[0]) <= P.EPS:
                vs.append(s)
            else:
                ds.append(s)
        dst = lambda s: self._dest_nodes(s[3].v)

        def bundle(s, t):
            """True if two segments belong to links that leave the same node or enter the same node."""
            return s[0][0] == t[0][0] or bool(dst(s) & dst(t))

        def dirty(x, s):
            """A crossing at x is too close to an end of segment s."""
            for pt, k in ((s[1], s[4]), (s[2], s[5])):
                d = P.NEAR_SOCK if k == 'sock' else P.NEAR_RR
                if k != 'lane' and _near(pt, x, d):
                    return True
            return False

        clean = bad = inbundle = 0
        for h in hs:
            y = h[1][1]
            x1, x2 = sorted((h[1][0], h[2][0]))
            for v in vs:
                if v[0] == h[0]:
                    continue
                x = v[1][0]
                y1, y2 = sorted((v[1][1], v[2][1]))
                if not (x1 + P.EPS < x < x2 - P.EPS and y1 + P.EPS < y < y2 - P.EPS):
                    continue
                if dirty((x, y), h) or dirty((x, y), v):
                    bad += 1
                else:
                    clean += 1
                if bundle(h, v):
                    inbundle += 1
        for d in ds:  # diagonal segments (none: every link is routed orthogonally)
            for t in hs + vs:
                if t[0] != d[0] and _segments_cross(d[1], d[2], t[1], t[2]):
                    bad += 1
                    if bundle(d, t):
                        inbundle += 1
        # collinear: two wires of different sources on one line (or almost)
        collinear = 0
        for group, axis in ((hs, 1), (vs, 0)):
            g = sorted(group, key=lambda s: s[1][axis])
            for a in range(len(g)):
                for b in range(a + 1, len(g)):
                    if g[b][1][axis] - g[a][1][axis] >= P.COLLINEAR:
                        break
                    if g[a][0] == g[b][0]:
                        continue
                    if _multi(g[a]) is not None and _multi(g[a]) == _multi(g[b]):
                        continue  # the links of one multi-input socket: its slots are this close
                    o = 1 - axis
                    lo = max(min(g[a][1][o], g[a][2][o]), min(g[b][1][o], g[b][2][o]))
                    hi = min(max(g[a][1][o], g[a][2][o]), max(g[b][1][o], g[b][2][o]))
                    if hi - lo > 1.0:
                        collinear += 1
        # reroute faults: bends of different wires at one point or too close, a bend on a wire
        pts = sorted(bends)
        clash = 0
        for a in range(len(pts)):
            if len(bends[pts[a]]) > 1:
                clash += len(bends[pts[a]]) - 1
            for b in range(a + 1, len(pts)):
                if pts[b][0] - pts[a][0] >= P.RR_CLEAR:
                    break
                if abs(pts[b][1] - pts[a][1]) < P.RR_CLEAR:
                    clash += 1
        on_wire = 0
        for pt, tags in bends.items():
            mine = multi.get(pt, ())
            for s in hs:
                if s[0] in tags or abs(s[1][1] - pt[1]) >= P.ON_WIRE or _multi(s) in mine:
                    continue
                if min(s[1][0], s[2][0]) + 1 < pt[0] < max(s[1][0], s[2][0]) - 1:
                    on_wire += 1
            for s in vs:
                if s[0] in tags or abs(s[1][0] - pt[0]) >= P.ON_WIRE:
                    continue
                if min(s[1][1], s[2][1]) + 1 < pt[1] < max(s[1][1], s[2][1]) - 1:
                    on_wire += 1
        return {"clean": clean, "bad": bad, "bundle": inbundle, "collinear": collinear,
                "clash": clash, "on_wire": on_wire}

    def cost(self):
        """One number for the quality of the current layout (lower is better). The parts are
        kept in self.cost_parts for inspection."""
        f = self.faults()
        bends = vlen = src = jogs = 0.0
        route = self._route()
        hlen = sum(abs(q[0] - p[0]) for _, p, q in route)
        border = self._on_border(route) if P.W_BORDER else 0
        for e in self.edges:
            d = abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False))
            if d > P.EPS:
                bends += 1
                vlen += d
                if d < P.JOG:
                    jogs += 1
                if getattr(e.u, 'src', False):
                    src += d
        reals = [i for i in self.items if not i.is_point]
        off = sum(1 for i in reals if abs(i.y / P.GRID - round(i.y / P.GRID)) > 1e-3)
        ys = [i.y for i in self.items] + [i.y + i.h for i in reals]
        xs = [i.x for i in self.items] + [i.x + i.w for i in reals]
        h = (max(ys) - min(ys)) if ys else 0.0
        w = (max(xs) - min(xs)) if xs else 0.0
        self.cost_parts = {**f, "bends": bends, "jogs": jogs, "vlen": vlen, "src": src,
                           "offgrid": off, "h": h, "w": w, "hlen": hlen,
                           "border": border}
        return (P.W_CROSS * f["clean"] + P.W_CROSS_BAD * f["bad"] + P.W_CROSS_BUNDLE * f["bundle"]
                + P.W_OVERLAP * f["collinear"] + P.W_CLASH * (f["clash"] + f["on_wire"])
                + P.W_BEND * bends + P.W_JOG * jogs + P.W_VLEN * vlen + P.W_SRC * src
                + P.W_GRID * off + P.W_H * h + P.W_W * w + P.W_HLEN * hlen
                + P.W_BORDER * border)


def _multi(s):
    """The multi-input socket that a detailed route segment ends at (the last run of a link into
    one of its slots), else None. These runs are only a slot apart, which is not a fault."""
    if s[5] != 'sock':
        return None
    key = slot_of(s[3].vk)
    return key[:3] if key is not None else None


def _segments_cross(a, b, c, d):
    """True if segments a-b and c-d cross at a single inner point."""
    def ccw(p, q, r):
        """Signed area of the triangle p, q, r (orientation test)."""
        return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    return ccw(c, d, a) * ccw(c, d, b) < 0 and ccw(a, b, c) * ccw(a, b, d) < 0
