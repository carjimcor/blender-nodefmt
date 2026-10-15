# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn route segments into reroute trees: one tree per source socket.

Segments come from every container level in absolute coordinates (y down). Points shared by
several links of the same source become taps; points where a route does not turn are dropped,
so a reroute exists only at a bend, a tap, or where a curve meets a straight run.
"""

from itertools import pairwise


def _r(p):
    """A point rounded to 0.1 units, so equal points compare equal."""
    return (round(p[0], 1), round(p[1], 1))


def _dir(p, q):
    """Direction of the step p -> q: ('h' | 'v', positive), or None for a diagonal."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    if abs(dy) < 0.05 and abs(dx) >= 0.05:
        return ("h", dx > 0)
    if abs(dx) < 0.05 and abs(dy) >= 0.05:
        return ("v", dy > 0)
    return None


class Tree:
    """The reroute tree of one source socket: points (reroutes, bends, taps) and the input sockets
    they lead to."""

    def __init__(self, tag):
        """An empty tree for source socket `tag`."""
        self.tag = tag
        self.children = {}  # point -> set(points)
        self.parent = {}  # point -> point
        self.dst = {}  # point -> destination key (a real input socket)
        self.root = None


def build(segments, roots):
    """segments: [(tag, p, q, dst)]; roots: tag -> source socket point. Returns {tag: Tree}."""
    trees = {}
    for tag, p, q, dst in segments:
        t = trees.setdefault(tag, Tree(tag))
        p, q = _r(p), _r(q)
        if p == q:
            if dst is not None:
                t.dst[q] = dst
            continue
        t.children.setdefault(p, set()).add(q)
        t.children.setdefault(q, set())
        if dst is not None:
            t.dst[q] = dst
    for tag, t in trees.items():
        t.root = _r(roots[tag])
        _fix_parents(t)
        _taps(t)
        _simplify(t)
    return trees


def _fix_parents(t):
    """Rebuild the parent map from the children map."""
    t.parent = {}
    for p, cs in t.children.items():
        for c in cs:
            t.parent[c] = p


def _taps(t):
    """Several branches leaving a point in the same direction share the nearer point."""
    changed = True
    while changed:
        changed = False
        for p in list(t.children):
            groups = {}
            for c in t.children[p]:
                d = _dir(p, c)
                if d:
                    groups.setdefault(d, []).append(c)
            for d, cs in groups.items():
                if len(cs) < 2:
                    continue
                cs.sort(key=lambda c: abs(c[0] - p[0]) + abs(c[1] - p[1]))
                for a, b in pairwise(cs):
                    if a in t.dst:
                        continue  # never route through a socket
                    t.children[p].discard(b)
                    t.children[a].add(b)
                    changed = True
                if changed:
                    break
            if changed:
                break
    _fix_parents(t)


def _simplify(t):
    """Drop points where a route goes straight on (they would be useless reroutes), and branches
    that lead nowhere."""
    changed = True
    while changed:
        changed = False
        for p in list(t.children):
            if p == t.root or p in t.dst or p not in t.parent:
                continue
            cs = t.children[p]
            if len(cs) != 1:
                continue
            c = next(iter(cs))
            a = t.parent[p]
            d1, d2 = _dir(a, p), _dir(p, c)
            if d1 is not None and d1 == d2:
                t.children[a].discard(p)
                t.children[a].add(c)
                t.parent[c] = a
                del t.children[p]
                del t.parent[p]
                changed = True

    # drop branches that lead to no destination (should not happen)
    def alive(p):
        """True if point p leads to a destination."""
        return p in t.dst or any(alive(c) for c in t.children.get(p, ()))

    for p in list(t.children):
        if p in t.children:
            t.children[p] = {c for c in t.children[p] if alive(c)}


def reroute_points(t):
    """Internal points of a tree (each becomes a reroute)."""
    return [p for p in t.children if p != t.root and p not in t.dst]


MARGIN = 40.0  # a label's own reroute sits this far along the wire from its start
CLEAR = 10.0  # a new label reroute keeps this far from other reroutes and wires


def place_labels(trees, labels, boxes=(), first=True, clear=True):
    """Put labelled reroutes back on the new routes (every reroute was removed for the layout).
    Returns {(source, point): (name, label)}.

    A label names a wire, and Blender 5 repeats it greyed on every later reroute of the wire, so
    one label near the start is enough. Labels of one source with the same text form a group;
    its label goes on the first reroute of the group's own part of the wire (after it splits
    from destinations outside the group), else of the whole wire (NF040, first=True; else the
    reroute nearest where the label was). With no reroute there, a new one goes MARGIN along
    the first horizontal run. The group's other labelled reroutes are dropped (blend.apply).

    A new reroute never puts its text over another label or a node, nor its dot near another
    wire or reroute. With clear (NF041), a label whose text would overlap a label or a node or
    be crossed by a wire (its own too) goes on a new reroute on the run before instead.

    trees: {source: Tree}; labels: label records from model.read; boxes: node boxes
    (x0, y0, x1, y1) that label text must not cover."""
    from . import labels as L

    out = {}
    texts = []  # boxes of the labels placed so far
    hsegs, vsegs = [], []
    for tag, t in trees.items():
        for p, cs in t.children.items():
            for c in cs:
                (hsegs if abs(p[1] - c[1]) < 0.05 else vsegs).append((tag, p, c))
    points = {(tag, p) for tag, t in trees.items() for p in reroute_points(t)}

    def clean(p, text):
        """True if the text of a label at point p overlaps no label placed so far, no node and
        no wire (the runs level with the dot are below the text)."""
        b = _label_box(p, text)
        return not (
            any(_overlap(b, o) for o in texts)
            or any(_overlap(b, o) for o in boxes)
            or any(L.hits(b, a, c) for _, a, c in hsegs + vsegs)
        )

    def free(tag, p, text):
        """True if a new reroute labelled `text` on wire `tag` at point p troubles nothing."""
        b = _label_box(p, text)
        if any(_overlap(b, o) for o in texts) or any(_overlap(b, o) for o in boxes):
            return False
        if clear and any(L.hits(b, a, c) for _, a, c in hsegs + vsegs):
            return False
        for _, q in points:
            if abs(q[0] - p[0]) < CLEAR and abs(q[1] - p[1]) < CLEAR:
                return False
        for tg, a, c in vsegs:
            if tg != tag and abs(a[0] - p[0]) < CLEAR and min(a[1], c[1]) - CLEAR < p[1] < max(a[1], c[1]) + CLEAR:
                return False
        for tg, a, c in hsegs:
            if tg != tag and abs(a[1] - p[1]) < CLEAR and min(a[0], c[0]) - CLEAR < p[0] < max(a[0], c[0]) + CLEAR:
                return False
        return True

    groups = {}
    for lab in labels:
        groups.setdefault((tuple(lab["src"]), lab["label"]), []).append(lab)
    for (src, text), labs in sorted(groups.items()):
        t = trees.get(src)
        if t is None:
            continue
        lab = min(labs, key=lambda lb: (lb["depth"], lb["x"], lb["name"]))  # the one nearest the source
        dsts = {tuple(d) for lb in labs for d in lb["dsts"]}
        pts = [p for p, d in t.dst.items() if d[:3] in dsts]
        if not pts:
            continue
        under = _subtree_dsts(t)
        mine = {t.dst[p] for p in pts}
        lca = _lca(t, pts)
        top = lca  # the highest point whose wire leads only to the group's destinations
        while top in t.parent and under[t.parent[top]] <= mine:
            top = t.parent[top]
        start = t.parent.get(top, top)
        path = _path(t, start, lca)
        # the first reroute of the group's own part of the wire, else of the whole wire
        own = [p for p in path[1:] if p in t.children and p not in t.dst and p != t.root]
        if not own:
            own = [p for p in _path(t, t.root, lca)[1:] if p in t.children and p not in t.dst]
        if own and not first:  # NF040 off: the reroute nearest to where the label was
            own = sorted(own, key=lambda q: (abs(q[0] - lab["x"]) + abs(q[1] - lab["y"]), q))

        def new(runs, t=t, src=src, text=text):
            """A new reroute near the start of the first horizontal run of `runs` where it
            troubles nothing (and is put on the tree), else None."""
            for a, b in runs:
                if abs(a[1] - b[1]) > 0.05 or abs(a[0] - b[0]) < 2.0:
                    continue
                sign = 1.0 if b[0] > a[0] else -1.0
                span = abs(b[0] - a[0])
                ds = [MARGIN + 20.0 * k for k in range(int(span // 20))] + [span / 2]
                if clear:  # any free spot along the run, the nearest to MARGIN first
                    ds += sorted((CLEAR * k for k in range(1, int(span // CLEAR))), key=lambda d: (abs(d - MARGIN), d))
                # the greyed copies Blender will show on the reroutes after it
                copies = [_label_box(c, text) for c in _below(t, b)] if clear else []
                for d in ds:
                    q = (round(a[0] + sign * d, 1), a[1])
                    if (
                        CLEAR <= d <= span - CLEAR
                        and free(src, q, text)
                        and not any(_overlap(_label_box(q, text), o) for o in copies)
                        and _insert(t, a, b, q)
                    ):
                        points.add((src, q))
                        return q
            return None

        p = None
        if own and clear:  # NF041: the first reroute where the text is clear, or a new reroute
            for q in own:  # on the run into it
                if clean(q, text):
                    p = q
                elif q in t.parent:
                    p = new([(t.parent[q], q)])
                if p is not None:
                    break
        if p is None and own:  # the first one whose text overlaps no other label (and, better, no node)
            ok = [q for q in own if not any(_overlap(_label_box(q, text), o) for o in texts)]
            p = next(
                (q for q in ok if not any(_overlap(_label_box(q, text), b) for b in boxes)), ok[0] if ok else own[0]
            )
        elif p is None:  # no reroute on the way: a new one near the start of the first horizontal run
            p = new(list(pairwise(path)))
            if p is None:
                continue
        out[(src, p)] = (lab["name"], lab["label"])
        texts.append(_label_box(p, lab["label"]))
    return out


def _below(t, p):
    """Point p and the reroute points after it in tree t (where a label put before p shows)."""
    out, todo = [], [p]
    while todo:
        q = todo.pop()
        if q != t.root and q not in t.dst and q in t.children:
            out.append(q)
        todo += list(t.children.get(q, ()))
    return out


def _label_box(p, text):
    """Box of a reroute label: centred above the dot, as Blender draws it (labels.box)."""
    from . import labels

    return labels.box(p, labels.text_width(text))


def _overlap(a, b):
    """True if boxes a and b overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _path(t, a, b):
    """Points from a down to b (a must be an ancestor of b, else just [b])."""
    chain = [b]
    while chain[-1] != a and chain[-1] in t.parent:
        chain.append(t.parent[chain[-1]])
    return chain[::-1] if chain[-1] == a else [b]


def _subtree_dsts(t):
    """For every point, the destination sockets below it."""
    memo = {}

    def go(p):
        """Destinations below point p (memoised)."""
        if p in memo:
            return memo[p]
        s = {t.dst[p]} if p in t.dst else set()
        for c in t.children.get(p, ()):
            s |= go(c)
        memo[p] = s
        return s

    go(t.root)
    for p in list(t.children):
        go(p)
    return memo


def _lca(t, pts):
    """Lowest common ancestor of several points of a tree."""

    def chain(p):
        """Point p and its ancestors up to the root."""
        c = [p]
        while c[-1] in t.parent:
            c.append(t.parent[c[-1]])
        return c

    common = None
    for p in pts:
        c = chain(p)
        common = c if common is None else [q for q in common if q in set(c)]
    return common[0]


def _insert(t, a, b, p):
    """Put point p on the horizontal run from a to b (which may already hold other points).
    Returns False if p is not on the run."""
    cur = a
    for _ in range(1000):
        if cur == b:
            return False
        nxt = next(
            (
                c
                for c in t.children.get(cur, ())
                if abs(c[1] - a[1]) < 0.05
                and min(a[0], b[0]) - 0.05 <= c[0] <= max(a[0], b[0]) + 0.05
                and c != cur
                and (c[0] - cur[0]) * (b[0] - a[0]) > 0
            ),
            None,
        )
        if nxt is None:
            return False
        if _between(cur, nxt, p):
            t.children[cur].discard(nxt)
            t.children[cur].add(p)
            t.children[p] = {nxt}
            t.parent[p] = cur
            t.parent[nxt] = p
            return True
        cur = nxt
    return False


def _between(a, b, p):
    """True if p lies strictly inside the horizontal run a-b."""
    return abs(a[1] - p[1]) < 0.05 and abs(b[1] - p[1]) < 0.05 and min(a[0], b[0]) < p[0] < max(a[0], b[0])
