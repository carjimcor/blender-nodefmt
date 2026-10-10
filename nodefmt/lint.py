# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks: which rules a drawn tree breaks, with the rule code and where (pure Python).

lint(drawing) looks at a wires.Drawing (a formatted layout, or a tree as Blender draws it, see
metrics.drawing) and returns Violations. NF010 and NF011 also need the tree's model data and
NF900 (not formatted) needs a format run; api.check adds those. Rules NF005 (logic), NF020
(zone outputs) and NF022 (shape) have no geometric test: a tree that breaks them is reported
as NF900, like any tree that formatting would change.
"""
from collections import namedtuple

from . import params as P
from . import routes, wires
from .rules import NAMES

# nodes: the names of the nodes involved (the Check panel selects them, with the reroutes at x, y)
Violation = namedtuple('Violation', 'code name msg x y nodes', defaults=((),))


def _v(code, msg, at=(0.0, 0.0), nodes=()):
    """A Violation of rule `code` at point `at` (y down; reported with Blender's y up), with the
    names of the nodes involved (None and duplicates dropped)."""
    names = tuple(dict.fromkeys(n for n in nodes if n is not None))
    return Violation(code, NAMES.get(code, "not-formatted"), msg, round(at[0], 1), round(-at[1], 1), names)


def _src(tag):
    """The node of a source socket tag."""
    return tag[0] if isinstance(tag, tuple) and tag else None


def _ends(s):
    """The source node of segment s and the nodes at its socket ends."""
    return (_src(s[0]), s[5], s[6])


def _name(tag):
    """Readable name of a source socket: 'Node:o0'."""
    return f"{tag[0]}:{tag[1]}{tag[2]}" if isinstance(tag, tuple) and len(tag) >= 3 else str(tag)


def lint(d, rules=None, labels=None, groups=None):
    """Violations of drawing d (wires.Drawing) for the enabled rule codes (default all).
    labels: {(tag, point): text} of labelled reroutes; groups: {frame: set of nodes}."""
    from .rules import DEFAULT
    rules = set(rules if rules is not None else DEFAULT)
    out = []
    segs = d.segments()
    rr = d.reroutes()
    # ------------------------------------------------ guarantees
    for s in segs:
        dx, dy = abs(s[1][0] - s[2][0]), abs(s[1][1] - s[2][1])
        mid = ((s[1][0] + s[2][0]) / 2, (s[1][1] + s[2][1]) / 2)
        if dx > 2.0 and dy > 2.0:
            out.append(_v('NF001', f"wire of {_name(s[0])} is drawn as a curve ({dx:.0f} x {dy:.0f})", mid, _ends(s)))
        elif dx > 0.5 and dy > 0.5:
            out.append(_v('NF003', f"segment of {_name(s[0])} is off by {min(dx, dy):.1f} units", mid, _ends(s)))
        for name, box in d.boxes.items():
            if name not in (s[5], s[6]) and wires.behind(s, box):
                out.append(_v('NF002', f"wire of {_name(s[0])} passes behind node {name!r}", mid, _ends(s) + (name,)))
                break
    for i in range(len(rr)):
        for j in range(i + 1, len(rr)):
            p, q = rr[i][1], rr[j][1]
            mp = wires.multi_at(d, rr[i][0], p)
            if mp is not None and mp == wires.multi_at(d, rr[j][0], q):
                continue  # the corners of the links into one multi-input socket are a slot apart
            if wires._near(p, q, P.RR_CLEAR) and ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 < P.RR_CLEAR:
                if rr[i][0] != rr[j][0]:
                    out.append(_v('NF004', f"reroutes of {_name(rr[i][0])} and {_name(rr[j][0])} overlap", p,
                                  (_src(rr[i][0]), _src(rr[j][0]))))
                elif 'NF031' in rules:  # one wire: a step too small to see, two reroutes on one spot
                    step = max(abs(p[0] - q[0]), abs(p[1] - q[1]))
                    out.append(_v('NF031', f"wire of {_name(rr[i][0])} steps by {step:.1f} units (two reroutes "
                                           f"on one spot)", p, (_src(rr[i][0]),)))
    # ------------------------------------------------ crossings: bundles (NF030)
    below = {tag: _below(d.trees[tag]) for tag in d.trees}

    def dests(s):
        """Destination nodes a segment leads to."""
        return below[s[0]].get(s[2], frozenset())
    hs = [s for s in segs if wires.horiz(s)]
    vs = [s for s in segs if wires.vert(s)]
    crosses = []
    for h in hs:
        for v in vs:
            if h[0] == v[0]:
                continue
            x = wires.crossing(h, v)
            if x is not None:
                crosses.append((h, v, x))
    if 'NF030' in rules:
        for h, v, x in crosses:
            if h[0][0] == v[0][0] or (dests(h) & dests(v)):
                out.append(_v('NF030', f"wires of {_name(h[0])} and {_name(v[0])} cross inside a bundle "
                                       f"(same source or destination node)", x, _ends(h) + _ends(v)))
    # ------------------------------------------------ jogs (NF031)
    if 'NF031' in rules:
        for tag in sorted(d.trees, key=repr):
            for kind, run, (y0, y2) in _jogs(d, tag):
                out.append(_v('NF031', f"wire of {_name(tag)}: {kind} at height {-run[0][1]:.0f} could "
                                       f"take the level {-y0:.0f} or {-y2:.0f}", run[0], (_src(tag),)))
    # ------------------------------------------------ clearance (NF032)
    if 'NF032' in rules:
        for s in segs:
            mid = ((s[1][0] + s[2][0]) / 2, (s[1][1] + s[2][1]) / 2)
            for name, box in sorted(d.boxes.items()):
                if name in (s[5], s[6]):
                    continue
                if not wires.behind(s, box) and wires.near_box(s, box) > P.CLEAR_NODE:
                    out.append(_v('NF032', f"wire of {_name(s[0])} runs along the edge of node {name!r}", mid,
                                  _ends(s) + (name,)))
            for name, poly in d.outlines:
                if wires.near_outline(s, poly) > P.CLEAR_RUN:
                    out.append(_v('NF032', f"wire of {_name(s[0])} runs along the border of {name!r}", mid, _ends(s)))
    # ------------------------------------------------ avoidable crossings (NF033)
    if 'NF033' in rules:
        for tag in sorted(d.trees, key=repr):
            n, at = _avoidable(d, tag)
            for _ in range(n):
                out.append(_v('NF033', f"a crossing of {_name(tag)} goes away if one of its runs moves to "
                                       f"another free height", at, (_src(tag),)))
    # ------------------------------------------------ junction look (NF034)
    if 'NF034' in rules:
        for k, a in enumerate(segs):
            for b in segs[k + 1:]:
                if a[0] != b[0] and wires.collinear(a, b) and not _multi_pair(d, a, b):
                    out.append(_v('NF034', f"wires of {_name(a[0])} and {_name(b[0])} run on one line", a[1],
                                  _ends(a) + _ends(b)))
        for tag, p in rr:
            mp = wires.multi_at(d, tag, p)
            for s in segs:
                if s[0] != tag and wires.on_segment(p, s, P.ON_WIRE) and (mp is None or wires.multi_of(d, s) != mp):
                    out.append(_v('NF034', f"a reroute of {_name(tag)} sits on the wire of {_name(s[0])}", p,
                                  (_src(tag),) + _ends(s)))
                    break
        for tag in sorted(d.trees, key=repr):
            t = d.trees[tag]
            for p in routes.reroute_points(t):
                if (tag, p) in (labels or {}):
                    continue
                a, cs = t.parent.get(p), t.children.get(p, ())
                if a is not None and len(cs) == 1 and wires._same_dir(a, p, next(iter(cs))):
                    out.append(_v('NF034', f"a reroute of {_name(tag)} sits in the middle of a straight run", p,
                                  (_src(tag),)))
    # ------------------------------------------------ blocks far from their consumer (NF021)
    if 'NF021' in rules and groups:
        for name, members in sorted(groups.items()):
            if not members or any(n not in d.boxes for n in members):
                continue
            ins = [t for t in d.trees.values() if t.tag[0] not in members
                   and any(t.dst[q][0] in members for q in t.dst)]
            outs = {d.dst_node(t.dst[q]) for tag, t in d.trees.items() if tag[0] in members
                    for q in t.dst} - set(members)
            if ins:
                continue
            if not outs:  # nothing linked at all: under the tree, as high as it fits
                if any(set(members) < set(o) for o in groups.values()):
                    continue  # a frame in another frame moves with it
                rise, at = _loose_rise(d, name, members)
                if rise > P.FAR_RISE:
                    out.append(_v('NF021', f"frame {name!r} has nothing linked and could sit {rise:.0f} units "
                                           f"higher, in the free space under the tree", at,
                                  (name,) + tuple(sorted(members))))
                continue
            right = max(d.boxes[n][2] for n in members)
            gap = min(d.boxes[n][0] for n in outs if n in d.boxes) - right if any(n in d.boxes for n in outs) else 0
            if gap > P.FAR_BLOCK:
                out.append(_v('NF021', f"frame {name!r} has no inputs and ends {gap:.0f} units before the node it "
                                       f"feeds", (right, min(d.boxes[n][1] for n in members)),
                              (name,) + tuple(sorted(members))))
    # ------------------------------------------------ labels (NF040)
    if 'NF040' in rules and labels:
        for (tag, p), text in sorted(labels.items(), key=lambda kv: (repr(kv[0][0]), kv[0][1])):
            t = d.trees.get(tag)
            if t is None or p not in t.parent:
                continue
            q = t.parent[p]
            while q != t.root and q in t.parent:
                if labels.get((tag, q)) == text:
                    out.append(_v('NF040', f"label {text!r} repeats a label upstream on its wire", p, (_src(tag),)))
                    break
                if len(t.children.get(q, ())) > 1:
                    break  # a tap: above it the wire leads elsewhere too
                if (tag, q) not in labels and ('NF041' not in rules or _readable(d, segs, q, text)):
                    out.append(_v('NF040', f"label {text!r} is not on the first reroute of its wire", p, (_src(tag),)))
                    break
                q = t.parent[q]
    # ------------------------------------------------ label clearance (NF041)
    if 'NF041' in rules and labels:
        out += _label_faults(d, segs, labels)
    return out


def _readable(d, segs, p, text):
    """True if a label at reroute p would be clear of nodes and wires (NF041): with NF041 a
    label may skip the reroutes before it where its text would not be."""
    from . import labels as L
    b = L.box(p, L.text_width(text))
    return not any(L.overlap(b, n) for n in d.boxes.values()) and not any(L.hits(b, s[1], s[2]) for s in segs)


def _label_faults(d, segs, labels):
    """NF041: the labels Blender shows (own and greyed copies, labels.shown) that overlap
    another label, a node or a wire."""
    from . import labels as L
    shown = []
    for tag in sorted(d.trees, key=repr):
        own = {p: text for (tg, p), text in labels.items() if tg == tag}
        if own:
            for p, (text, inherited) in sorted(L.shown(d.trees[tag], own).items()):
                shown.append((tag, p, text, inherited))
    what = {'label': "another label", 'node': "a node", 'wire': "a wire"}
    out = []
    for k, kind in L.faults([(p, text, inh) for _, p, text, inh in shown], list(d.boxes.values()),
                            [(s[1], s[2]) for s in segs]):
        tag, p, text, inherited = shown[k]
        copy = "its greyed copy " if inherited else ""
        out.append(_v('NF041', f"label {text!r} of {_name(tag)}: {copy}overlaps {what[kind]}", p, (_src(tag),)))
    return out


def _loose_rise(d, name, members):
    """How much higher frame `name` (nothing linked into or out of it) could sit under the tree,
    in the free space below what is above it, within the tree's width; and a point to report."""
    rect = None
    for n, poly in d.outlines:
        if n == name:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            rect = (min(xs), min(ys), max(xs), max(ys))
    if rect is None:
        return 0.0, (0.0, 0.0)
    w, h = rect[2] - rect[0], rect[3] - rect[1]

    def inside(r):
        """True if box r lies within the frame."""
        return rect[0] - 1 <= r[0] and r[2] <= rect[2] + 1 and rect[1] - 1 <= r[1] and r[3] <= rect[3] + 1
    occ = [b for n, b in d.boxes.items() if n not in members]
    occ += [(min(s[1][0], s[2][0]), min(s[1][1], s[2][1]), max(s[1][0], s[2][0]), max(s[1][1], s[2][1]))
            for s in d.segments()]
    for n, poly in d.outlines:
        r = (min(p[0] for p in poly), min(p[1] for p in poly), max(p[0] for p in poly), max(p[1] for p in poly))
        if n != name and not inside(r) and not (r[0] <= rect[0] and rect[2] <= r[2] and r[1] <= rect[1] and rect[3] <= r[3]):
            occ.append(r)
    occ = [r for r in occ if not inside(r)]
    if not occ:
        return 0.0, (0.0, 0.0)
    x0, x1 = min(r[0] for r in occ + [rect]), max(r[2] for r in occ + [rect])
    best = rect[1]
    for x in sorted({x0} | {r[2] + P.COL_GAP for r in occ}):
        if x + w > x1:
            continue
        below = [r[3] for r in occ if r[0] < x + w + P.COL_GAP and r[2] > x - P.COL_GAP]
        y = (max(below) if below else min(r[1] for r in occ)) + P.COL_GAP
        if not any(r[0] < x + w and x < r[2] and r[1] < y + h and y < r[3] for r in occ):
            best = min(best, y)
    return rect[1] - best, (rect[0], rect[1])


def counts(vs):
    """{code: number of violations}, sorted by code."""
    out = {}
    for v in vs:
        out[v.code] = out.get(v.code, 0) + 1
    return dict(sorted(out.items()))


def report(vs, prefix=""):
    """Lines like ruff's: 'prefix: NF031 no-u-jogs  message  at (x, y)'."""
    return [f"{prefix}{v.code} {v.name}: {v.msg} at ({v.x:g}, {v.y:g})" for v in vs]


# ---------------------------------------------------------------- helpers
def _below(t):
    """For every point of tree t, the destination nodes below it."""
    memo = {}

    def go(p, depth=0):
        """Destination nodes below point p."""
        if p in memo:
            return memo[p]
        s = {t.dst[p][0]} if p in t.dst else set()
        if depth < 500:
            for c in t.children.get(p, ()):
                s |= go(c, depth + 1)
        memo[p] = frozenset(s)
        return memo[p]
    for p in list(t.children):
        go(p)
    return memo


def _multi_pair(d, a, b):
    """True if two segments are the last runs into one multi-input socket (a slot apart)."""
    if a[4] != 'sock' or b[4] != 'sock':
        return False
    ka, kb = d.trees[a[0]].dst.get(a[2]), d.trees[b[0]].dst.get(b[2])
    return ka is not None and kb is not None and len(ka) == 4 and len(kb) == 4 and ka[:3] == kb[:3]


def _jogs(d, tag):
    """Reversals and landings of one tree that moving their run to another height removes
    without any other fault: [(kind, run, (level before, level after))]."""
    t = d.trees[tag]
    others = [s for s in d.segments() if s[0] != tag]
    other_rr = [(g, p) for g, p in d.reroutes() if g != tag]
    base = wires.tree_faults(d, tag, others, other_rr)
    if not base["reversals"] and not base["landings"]:
        return []
    rev, land = wires.jogs(t)
    keys = ("behind", "touch", "collinear", "on_wire", "clash", "near_node", "near_outline", "cross", "cross_bad")
    out = []
    for pa, a, b, c in wires._runs(t):
        if (a, b) not in rev and (a, b) not in land:
            continue
        edges = [(p, q) for p, cs in t.children.items() for q in cs]
        for y in wires._levels(d, pa, a, b, c):
            ren = {a: (a[0], y), b: (b[0], y)}
            old = ({k: set(v) for k, v in t.children.items()}, dict(t.parent))
            try:
                wires._rebuild(t, [(ren.get(p, p), ren.get(q, q)) for p, q in edges])
                f = wires.tree_faults(d, tag, others, other_rr)
            except (ValueError, RecursionError):
                f = None
            t.children, t.parent = old
            if f is None:
                continue
            if f["reversals"] + f["landings"] < base["reversals"] + base["landings"]                     and all(f[k] <= base[k] for k in keys):
                out.append(("U-jog" if (a, b) in rev else "landing", (a, b), (pa[1], c[1])))
                break
    return out


def _avoidable(d, tag):
    """(crossings of tree `tag` that moving one of its runs to another height removes without
    any other fault, a point to report)."""
    t = d.trees[tag]
    others = [s for s in d.segments() if s[0] != tag]
    other_rr = [(g, p) for g, p in d.reroutes() if g != tag]
    base = wires.tree_faults(d, tag, others, other_rr)
    c0 = base["cross"] + base["cross_bad"]
    if not c0:
        return 0, (0.0, 0.0)
    best, at = 0, (0.0, 0.0)
    keys = ("behind", "touch", "collinear", "on_wire", "clash", "near_node", "near_outline")
    for pa, a, b, c in wires._runs(t):
        edges = [(p, q) for p, cs in t.children.items() for q in cs]
        for y in wires._levels(d, pa, a, b, c):
            ren = {a: (a[0], y), b: (b[0], y)}
            old = ({k: set(v) for k, v in t.children.items()}, dict(t.parent))
            try:
                wires._rebuild(t, [(ren.get(p, p), ren.get(q, q)) for p, q in edges])
                f = wires.tree_faults(d, tag, others, other_rr)
            except (ValueError, RecursionError):
                f = None
            t.children, t.parent = old
            if f is None:
                continue
            gain = c0 - f["cross"] - f["cross_bad"]
            if gain > best and all(f[k] <= base[k] for k in keys):
                best, at = gain, a
    return best, at
