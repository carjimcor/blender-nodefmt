# SPDX-License-Identifier: GPL-3.0-or-later
"""The drawn wires of a whole tree (pure Python): faults, and the route tidy pass.

A Drawing holds one reroute tree per source socket (routes.Tree, points y down), the node boxes
and the outlines of zones and frames. It is built from a layout (layout.Formatter, before the
reroutes are written) or from a tree as Blender draws it (metrics.drawing), so the tidy pass and
the checks (lint.py) see the same thing.

The tidy pass works across containers, where the layout engine cannot see: a wire that leaves a
zone or frame, or enters one, is routed in two pieces that meet at the border. It moves single
horizontal runs (a run between two vertical bends) to another height when that makes the whole
drawing better, and it puts the runs that are almost level exactly level:

  NF031 no-u-jogs        a run between two steps in the same direction (a landing) merges with
                         the level before or after it; a route reverses its vertical direction
                         only where a node is in the way
  NF032 wire-clearance   no run along a node's edge, a frame's border or a zone's outline
  NF033 avoid-crossings  a run takes the free height where it crosses the fewest wires
  NF034 no-junction-look two wires never share a point or run on one line; no reroute sits in
                         the middle of a straight run
"""
from . import params as P
from . import routes

E = 0.05  # points closer than this are the same (routes rounds to 0.1)


class Drawing:
    """The wires of one tree as drawn (see the module docstring)."""

    def __init__(self, trees, boxes, outlines=(), src_node=None, dst_node=None):
        """trees: {tag: routes.Tree}; boxes: {node: (x0, y0, x1, y1)}; outlines: [(name,
        [(x, y), ...])] closed polygons of zones and frames."""
        self.trees = trees
        self.boxes = boxes
        self.outlines = list(outlines)
        # node of a source tag and of a destination key (for the clearance of a wire's own ends)
        self.src_node = src_node or (lambda tag: tag[0])
        self.dst_node = dst_node or (lambda key: key[0])

    # ------------------------------------------------------------ segments
    def tree_segments(self, tag):
        """Drawn segments of one tree: [(tag, p, q, p_kind, q_kind, p_node, q_node)], kind 'sock'
        (a socket) or 'rr' (a reroute); *_node is the node of a socket end, else None."""
        t = self.trees[tag]
        out = []
        for p, cs in t.children.items():
            for q in cs:
                pk = 'sock' if p == t.root else 'rr'
                qk = 'sock' if q in t.dst else 'rr'
                out.append((tag, p, q, pk, qk, self.src_node(tag) if pk == 'sock' else None,
                            self.dst_node(t.dst[q]) if qk == 'sock' else None))
        return out

    def segments(self):
        """Segments of every tree."""
        return [s for tag in sorted(self.trees, key=repr) for s in self.tree_segments(tag)]

    def reroutes(self, tag=None):
        """Reroute points [(tag, point)] of one tree or of all."""
        tags = [tag] if tag is not None else sorted(self.trees, key=repr)
        return [(t, p) for t in tags for p in routes.reroute_points(self.trees[t])]


# ---------------------------------------------------------------- geometry
def horiz(s):
    """True if segment s is horizontal (and not a point)."""
    return abs(s[1][1] - s[2][1]) <= 0.5 and abs(s[1][0] - s[2][0]) > 0.5


def vert(s):
    """True if segment s is vertical (and not a point)."""
    return abs(s[1][0] - s[2][0]) <= 0.5 and abs(s[1][1] - s[2][1]) > 0.5


def crossing(h, v):
    """The point where horizontal h and vertical v cross inside both, else None."""
    y = h[1][1]
    x1, x2 = sorted((h[1][0], h[2][0]))
    x = v[1][0]
    y1, y2 = sorted((v[1][1], v[2][1]))
    if x1 + 0.5 < x < x2 - 0.5 and y1 + 0.5 < y < y2 - 0.5:
        return (x, y)
    return None


def _near(p, q, d):
    """True if p and q are closer than d along both axes."""
    return abs(p[0] - q[0]) < d and abs(p[1] - q[1]) < d


def dirty(x, s):
    """True if crossing point x is near an end of segment s (a socket or a bend)."""
    for pt, k in ((s[1], s[3]), (s[2], s[4])):
        if _near(pt, x, P.NEAR_SOCK if k == 'sock' else P.NEAR_RR):
            return True
    return False


def collinear(a, b):
    """True if two segments run on one line (or closer than COLLINEAR) over more than a unit."""
    for axis in (1, 0):
        if (horiz(a) and horiz(b)) if axis == 1 else (vert(a) and vert(b)):
            if abs(a[1][axis] - b[1][axis]) >= P.COLLINEAR:
                return False
            o = 1 - axis
            lo = max(min(a[1][o], a[2][o]), min(b[1][o], b[2][o]))
            hi = min(max(a[1][o], a[2][o]), max(b[1][o], b[2][o]))
            return hi - lo > 1.0
    return False


def on_segment(p, s, d):
    """True if point p lies within d of segment s, away from its ends."""
    (x1, y1), (x2, y2) = s[1], s[2]
    if _near(p, s[1], 1.0) or _near(p, s[2], 1.0):
        return False
    if abs(y1 - y2) <= 0.5:
        return abs(p[1] - y1) < d and min(x1, x2) + 1 < p[0] < max(x1, x2) - 1
    if abs(x1 - x2) <= 0.5:
        return abs(p[0] - x1) < d and min(y1, y2) + 1 < p[1] < max(y1, y2) - 1
    return False


def behind(s, box, m=2.0):
    """True if segment s passes through the inside of box (shrunk by m)."""
    x0, y0, x1, y1 = box[0] + m, box[1] + m, box[2] - m, box[3] - m
    (ax, ay), (bx, by) = s[1], s[2]
    if abs(ay - by) <= 0.5:
        return y0 < ay < y1 and min(ax, bx) < x1 and max(ax, bx) > x0
    if abs(ax - bx) <= 0.5:
        return x0 < ax < x1 and min(ay, by) < y1 and max(ay, by) > y0
    return False


def near_box(s, box):
    """Length of segment s that runs along an edge of box closer than CLEAR_NODE (outside it)."""
    c = P.CLEAR_NODE
    (ax, ay), (bx, by) = s[1], s[2]
    if abs(ay - by) <= 0.5:
        d = min(abs(ay - box[1]), abs(ay - box[3]))
        if d >= c or box[1] < ay < box[3]:
            return 0.0
        return max(0.0, min(max(ax, bx), box[2]) - max(min(ax, bx), box[0]))
    if abs(ax - bx) <= 0.5:
        d = min(abs(ax - box[0]), abs(ax - box[2]))
        if d >= c or box[0] < ax < box[2]:
            return 0.0
        return max(0.0, min(max(ay, by), box[3]) - max(min(ay, by), box[1]))
    return 0.0


def _dist_seg(p, a, b):
    """Distance from point p to segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5


def near_outline(s, poly):
    """Length of segment s that runs closer than CLEAR_OUTLINE to the border of polygon poly
    (sampled every 4 units). A wire that crosses the border at an angle stays near it briefly;
    one that runs along it, long."""
    (ax, ay), (bx, by) = s[1], s[2]
    c = P.CLEAR_OUTLINE
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    if not poly or max(ax, bx) < min(xs) - c or min(ax, bx) > max(xs) + c             or max(ay, by) < min(ys) - c or min(ay, by) > max(ys) + c:
        return 0.0
    L = abs(ax - bx) + abs(ay - by)
    n = max(1, int(L // 4))
    near = 0
    edges = list(zip(poly, poly[1:] + poly[:1]))
    for k in range(n + 1):
        t = k / n
        p = (ax + (bx - ax) * t, ay + (by - ay) * t)
        if any(_dist_seg(p, a, b) < P.CLEAR_OUTLINE for a, b in edges):
            near += 1
    return near * L / (n + 1)


def hull(points):
    """Convex hull of points (monotone chain), counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        """z of (a - o) x (b - o)."""
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def zone_outline(inp, out, content):
    """The outline Blender draws around a zone (node_draw.cc, find_bounds_by_zone): the content
    nodes padded by a widget unit, the input node from a quarter of its width and the output
    node up to three quarters, both padded sideways by 0.3 units. Boxes (x0, y0, x1, y1)."""
    pad, zp = 20.0, 6.0
    pts = []
    for b in content:
        pts += [(b[0] - pad, b[1] - pad), (b[2] + pad, b[1] - pad), (b[0] - pad, b[3] + pad), (b[2] + pad, b[3] + pad)]
    if inp is not None:
        x0 = inp[0] + 0.25 * (inp[2] - inp[0])
        pts += [(x0, inp[1]), (inp[2] + zp, inp[1]), (x0, inp[3]), (inp[2] + zp, inp[3])]
    if out is not None:
        x1 = out[0] + 0.75 * (out[2] - out[0])
        pts += [(out[0] - zp, out[1]), (x1, out[1]), (out[0] - zp, out[3]), (x1, out[3])]
    return hull(pts)


# ---------------------------------------------------------------- paths
def paths(t):
    """Every route of tree t from its root to a destination, as a list of points."""
    out = []
    for q in sorted(t.dst):
        chain = [q]
        while chain[-1] in t.parent and len(chain) < 1000:
            chain.append(t.parent[chain[-1]])
        out.append(chain[::-1])
    return out


def steps(path):
    """The vertical moves of a route with the horizontal run between each two:
    [(dir, run)], dir +1 down or -1 up, run = (a, b) the horizontal run before the move
    (None for the first)."""
    pts = [path[0]]
    for p in path[1:]:
        if len(pts) >= 2 and _same_dir(pts[-2], pts[-1], p):
            pts[-1] = p
        else:
            pts.append(p)
    out = []
    run = None
    for a, b in zip(pts, pts[1:]):
        if abs(a[0] - b[0]) <= 0.5 and abs(a[1] - b[1]) > 0.5:
            out.append((1 if b[1] > a[1] else -1, run))
            run = None
        elif abs(a[1] - b[1]) <= 0.5:
            run = (a, b)
    return out


def _same_dir(a, b, c):
    """True if a-b and b-c go the same way (both horizontal or both vertical, same sense)."""
    d1 = routes._dir(a, b)
    d2 = routes._dir(b, c)
    return d1 is not None and d1 == d2


def jogs(t):
    """(reversals, landings) of tree t: horizontal runs between two vertical moves in opposite
    directions (a U or an inverted U) and in the same direction (a step with a landing), each
    run counted once."""
    rev, land = set(), set()
    for path in paths(t):
        st = steps(path)
        for (d1, _), (d2, run) in zip(st, st[1:]):
            if run is None:
                continue
            (rev if d1 != d2 else land).add(run)
    return rev, land


# ---------------------------------------------------------------- faults of one tree
def multi_at(d, tag, p):
    """The multi-input socket (gid) a reroute's last run enters, else None."""
    t = d.trees[tag]
    for q in t.children.get(p, ()):
        k = t.dst.get(q)
        if k is not None and len(k) == 4:
            return k[:3]
    return None


def multi_of(d, s):
    """The multi-input socket a segment ends at, else None."""
    if s[4] != 'sock':
        return None
    k = d.trees[s[0]].dst.get(s[2])
    return k[:3] if k is not None and len(k) == 4 else None


def tree_faults(d, tag, others=None, other_rr=None):
    """Faults of the wires of one tree against the rest of the drawing (and its own jogs):
    a dict of counts. others: segments of the other trees; other_rr: their reroutes."""
    segs = d.tree_segments(tag)
    if others is None:
        others = [s for s in d.segments() if s[0] != tag]
    if other_rr is None:
        other_rr = [(g, p) for g, p in d.reroutes() if g != tag]
    mine_rr = routes.reroute_points(d.trees[tag])
    f = {"cross": 0, "cross_bad": 0, "collinear": 0, "on_wire": 0, "clash": 0, "behind": 0, "touch": 0,
         "near_node": 0, "near_outline": 0, "reversals": 0, "landings": 0, "vlen": 0.0, "reroutes": len(mine_rr)}
    for s in segs:
        if vert(s):
            f["vlen"] += abs(s[1][1] - s[2][1])
        for o in others:
            x = None
            if horiz(s) and vert(o):
                x = crossing(s, o)
            elif vert(s) and horiz(o):
                x = crossing(o, s)
            if x is not None:
                if dirty(x, s) or dirty(x, o):
                    f["cross_bad"] += 1
                else:
                    f["cross"] += 1
            elif collinear(s, o):
                f["collinear"] += 1
        ms = multi_of(d, s)
        for g, p in other_rr:
            if on_segment(p, s, P.ON_WIRE) and (ms is None or multi_at(d, g, p) != ms):
                f["on_wire"] += 1
        for name, box in d.boxes.items():
            if name in (s[5], s[6]):
                continue
            if behind(s, box):
                f["behind"] += 1
            elif behind(s, box, -P.TOUCH):
                f["touch"] += 1  # on the edge: a pixel off and it is behind the node
            elif near_box(s, box) > P.CLEAR_NODE:
                f["near_node"] += 1
        for _, poly in d.outlines:
            if near_outline(s, poly) > P.CLEAR_RUN:
                f["near_outline"] += 1
    for k, p in enumerate(mine_rr):
        for q in mine_rr[k + 1:]:
            if _near(p, q, P.RR_CLEAR):
                f["clash"] += 1  # two bends of one wire this close look like one blob
        mp = multi_at(d, tag, p)
        for o in others:
            if on_segment(p, o, P.ON_WIRE) and (mp is None or multi_of(d, o) != mp):
                f["on_wire"] += 1
        for _, q in other_rr:
            if _near(p, q, P.RR_CLEAR):
                f["clash"] += 1
    rev, land = jogs(d.trees[tag])
    f["reversals"], f["landings"] = len(rev), len(land)
    return f


FAULTS = ("cross", "cross_bad", "collinear", "on_wire", "clash", "near_node", "near_outline", "reversals", "landings")


def score(f, rules):
    """One number for the faults of a tree (lower is better); rules switch parts off."""
    s = 1000.0 * (f["behind"] + f["touch"]) + 1.0 * f["reroutes"] + 0.005 * f["vlen"]
    if 'NF033' in rules:
        s += 10.0 * f["cross"] + 15.0 * f["cross_bad"]
    if 'NF034' in rules:
        s += 40.0 * (f["collinear"] + f["on_wire"] + f["clash"])
    if 'NF032' in rules:
        s += 12.0 * f["near_node"] + 8.0 * f["near_outline"]
    if 'NF031' in rules:
        s += 4.0 * f["reversals"] + 4.0 * f["landings"]
    return s


# ---------------------------------------------------------------- tidy
def snap_level(d):
    """NF034: runs that are almost level (within a unit) become exactly level, at the height of
    the socket they start or end at (the source first), so no reroute is left in the middle of
    a straight run. Returns the number of points moved."""
    moved = 0
    for tag in sorted(d.trees, key=repr):
        t = d.trees[tag]
        edges = [(p, q) for p, cs in t.children.items() for q in cs]
        adj = {}
        for p, q in edges:
            if abs(p[1] - q[1]) <= 1.0 and abs(p[0] - q[0]) > 0.5:
                adj.setdefault(p, set()).add(q)
                adj.setdefault(q, set()).add(p)
        seen, ren = set(), {}
        for p in sorted(adj):
            if p in seen:
                continue
            group, todo = set(), [p]
            while todo:
                x = todo.pop()
                if x in group:
                    continue
                group.add(x)
                todo += list(adj.get(x, ()))
            seen |= group
            ys = {round(x[1], 1) for x in group}
            if len(ys) < 2:
                continue
            if t.root in group:
                y = t.root[1]
            else:
                socks = sorted(x for x in group if x in t.dst)
                if not socks:
                    continue
                y = socks[0][1]
            for x in group:
                if x != t.root and x not in t.dst and abs(x[1] - y) > 0.01:
                    ren[x] = (x[0], y)
        if ren:
            moved += len(ren)
            _rebuild(t, [(ren.get(p, p), ren.get(q, q)) for p, q in edges])
    return moved


def _rebuild(t, edges):
    """Tree t from a new list of edges (points renamed): duplicates and loops dropped, then taps
    and straight-through points as in routes.build."""
    t.children = {}
    for p, q in edges:
        p, q = routes._r(p), routes._r(q)
        t.children.setdefault(q, set())
        if p != q:
            t.children.setdefault(p, set()).add(q)
    # a move that makes a route run into itself is not a tree any more
    state, stack = {}, [(t.root, iter(t.children.get(t.root, ())))]
    state[t.root] = 1
    while stack:
        p, it = stack[-1]
        c = next(it, None)
        if c is None:
            state[p] = 2
            stack.pop()
        elif state.get(c) == 1:
            raise ValueError("loop")
        elif c not in state:
            state[c] = 1
            stack.append((c, iter(t.children.get(c, ()))))
    routes._fix_parents(t)
    routes._taps(t)
    routes._simplify(t)
    for p in [p for p in t.children if p != t.root and p not in t.parent and p not in t.dst]:
        del t.children[p]  # left alone by a merge
    routes._fix_parents(t)


def _runs(t):
    """Horizontal runs of tree t that may move up or down: (pa, a, b, c) with a vertical
    pa -> a, the run a -> b and a vertical b -> c, where a and b are plain bends."""
    out = []
    for a, cs in t.children.items():
        if a == t.root or a in t.dst or len(cs) != 1 or a not in t.parent:
            continue
        b = next(iter(cs))
        pa = t.parent[a]
        if b in t.dst or abs(a[1] - b[1]) > E or abs(pa[0] - a[0]) > E:
            continue
        bc = t.children.get(b, set())
        if len(bc) != 1:
            continue
        c = next(iter(bc))
        if abs(c[0] - b[0]) > E:
            continue
        out.append((pa, a, b, c))
    return sorted(out)


def _levels(d, pa, a, b, c):
    """Heights a run from x = a to x = b may take: the levels before and after it, and just
    above or below every node box in its way (a lane gap away)."""
    x0, x1 = sorted((a[0], b[0]))
    ys = {pa[1], c[1]}
    g = P.LANE_GAP
    for box in d.boxes.values():
        if box[0] < x1 + g and box[2] > x0 - g:
            ys.add(round(box[1] - g, 1))
            ys.add(round(box[3] + g, 1))
    lo, hi = min(pa[1], c[1], a[1]) - 400.0, max(pa[1], c[1], a[1]) + 400.0
    near = sorted((y for y in ys - {pa[1], c[1]} if lo <= y <= hi), key=lambda y: (abs(y - a[1]), y))[:6]
    return sorted(y for y in set(near) | {pa[1], c[1]} if abs(y - a[1]) > 0.5)


def tidy(d, rules, passes=4):
    """Move runs to better heights (see the module docstring) until nothing improves. Returns
    the number of moves. Deterministic: trees and runs in sorted order."""
    if not ({'NF031', 'NF032', 'NF033', 'NF034'} & set(rules)):
        return 0  # no wire rule on: the drawing stays as the layout made it
    moves = 0
    for _ in range(passes):
        changed = False
        for tag in sorted(d.trees, key=repr):
            t = d.trees[tag]
            others = [s for s in d.segments() if s[0] != tag]
            other_rr = [(g, p) for g, p in d.reroutes() if g != tag]
            for _ in range(20):
                f0 = tree_faults(d, tag, others, other_rr)
                if not any(f0[k] for k in FAULTS):
                    break  # nothing to mend in this tree
                base = score(f0, rules)
                best = None
                for pa, a, b, c in _runs(t):
                    edges = [(p, q) for p, cs in t.children.items() for q in cs]
                    for y in _levels(d, pa, a, b, c):
                        a2, b2 = (a[0], y), (b[0], y)
                        ren = {a: a2, b: b2}
                        old = ({k: set(v) for k, v in t.children.items()}, dict(t.parent))
                        try:
                            _rebuild(t, [(ren.get(p, p), ren.get(q, q)) for p, q in edges])
                            sc = score(tree_faults(d, tag, others, other_rr), rules)
                        except (ValueError, RecursionError):
                            sc = None
                        t.children, t.parent = old
                        if sc is None:
                            continue
                        if sc < base - 1e-6 and (best is None or sc < best[0] - 1e-6):
                            best = (sc, edges, ren)
                if best is None:
                    break
                _, edges, ren = best
                _rebuild(t, [(ren.get(p, p), ren.get(q, q)) for p, q in edges])
                moves += 1
                changed = True
        if not changed:
            break
    return moves
