# SPDX-License-Identifier: GPL-3.0-or-later
"""Layered layout of one container (the tree, a zone or a frame), in pure Python.

Coordinates: x to the right, y DOWN (y = -blender_y), an item's position is its top-left corner.
The layout of a container is a Sugiyama-style layered drawing with orthogonal routing:

  ranking.py    columns (longest-path ranks), and lanes (dummies) for links spanning columns
  ordering.py   order of each column: barycenter sweeps, transposition, commutative swaps
  force.py      another order: force-directed relaxation of heights, sorted
  placement.py  heights: blocks of straight links + compaction ('blocks', 'balanced')
  relax.py      heights: spring relaxation + straightening ('relax')
  columns.py    x of columns and of the routing tracks in each gap (track order)
  cost.py       routes and the weighted faults of a layout
  search.py     local search over the choices above, and the final slide pass

layout() runs them for several seeds and keeps the cheapest layout. Every link that is not
straight turns on a vertical track in the gap after its source column, so no link passes behind
a node, and every segment is horizontal or vertical (into a multi-input socket too: the link
turns at its slot's height). In a zone, the
zone input heads the first column and the zone's content hangs below its top line.
"""
import random
import time

from . import params as P
from .columns import ColumnsMixin
from .cost import CostMixin
from .force import ForceMixin
from .graph import Cand, CycleError, Edge, Item, LayoutBase, PORT_DIRECT, Result, snap_down, snap_up
from .graph import _name as _name_key
from .ordering import OrderingMixin
from .placement import PlacementMixin
from .ranking import RankingMixin
from .relax import RelaxMixin
from .search import SearchMixin

GRID = P.GRID  # kept for callers (layout.py)
# what layout.py uses from here
__all__ = ['layout', 'snapshot_state', 'Item', 'Edge', 'CycleError', 'PORT_DIRECT', 'GRID', 'Result']


def layout(items, edges, mode='relayout', pad=(0, 0, 0, 0), snapshot=None, labels=None):
    """Lay out the items of one container. pad = (left, top, right, bottom) is reserved around
    the content (frames). Returns a Result with item positions, route segments and the box.

    Steps: ranks, lanes (bus dummies) for long links, then for each seed (P.SEEDS; seed 0 is the
    plain deterministic run, others jitter the initial order and shuffle the search moves): the
    best orders of the crossing reduction are laid out in full with each placement method, the
    cheapest is improved by a short local search (P.SEARCH_SEED layouts). The best result of all
    seeds gets the full local search (P.SEARCH layouts) and the slide pass. Everything is
    deterministic (seeded generators, budgets counted in layouts, not seconds), so formatting a
    formatted tree changes nothing.

    In a zone, every candidate is also tried with each zone output mode (P.ZONE_OUT). The modes
    form two groups, searched apart in every seed: 'level' (the output on the zone input's line)
    and 'free' ('median' or 'mean', whichever starts cheaper). Each group's best gets the full
    search and the slide. The Result is the cheaper group; res.alts lists both groups with their
    costs and res.realize(group) gives the other one, so the parent container can pick the group
    that suits what follows the zone (layout.py). P.SEED_ONLY runs one seed only (tests).

    snapshot, if given, is called as snapshot(phase, state) with plain data of the layout after
    each phase ('order', 'placement', 'seed <n>', 'search', 'slide'); see snapshot_state().
    labels: {source tag: text width} of the labelled wires (NF041, cost.py and columns.py).

    A child block with commutative pairs at its border (layout.py, NF011) is laid out with the
    pairs as the block left them and with the pairs free; the cheaper of the two fresh layouts
    decides (exchanging them can lead the search elsewhere, to a worse layout)."""
    t0 = time.perf_counter()
    border = [i for i in items if i.kind == 'compound' and getattr(i, 'comm', None)] if mode == 'relayout' else []
    if not border:
        return _choose(items, edges, mode, pad, snapshot, t0, labels)
    saved = {id(i): i.comm for i in border}

    def fix(on):
        """The border pairs as the blocks left them (on) or free."""
        for i in border:
            i.comm = None if on else saved[id(i)]
    fix(True)
    fixed = _choose(items, edges, mode, pad, None, t0, labels, stable=False)
    fix(False)
    free = _choose(items, edges, mode, pad, None, t0, labels, stable=False)
    fix(fixed.cost <= free.cost + 1e-9)
    try:
        return _choose(items, edges, mode, pad, snapshot, t0, labels)
    finally:
        fix(False)


def _choose(items, edges, mode, pad, snapshot, t0, labels, stable=True):
    """layout() of the items as they are: with and without satellites (NF021)."""
    # NF021: blocks with no inputs may sit next to their consumer (satellites, ranking.py); the
    # container is laid out with and without them and the cheaper layout is kept
    sats = P.SATELLITES and mode == 'relayout' and any(
        i.kind == 'compound' and getattr(i, 'big', False) and i.pin is None
        and not any(e.v is i for e in edges) and any(e.u is i for e in edges) for i in items)
    if not sats:
        return _layout(items, edges, mode, pad, snapshot, False, t0, stable=stable, labels=labels)
    # the choice between the two is made on fresh layouts only (no stability start), so that
    # switching NF021 off and on again gives the same result
    plain = _layout(items, edges, mode, pad, None, False, t0, stable=False, labels=labels)
    res = _layout(items, edges, mode, pad, None, True, t0, stable=False, labels=labels)
    return _layout(items, edges, mode, pad, snapshot, plain.cost >= res.cost - 1e-9, t0, stable=stable,
                   labels=labels)


def _layout(items, edges, mode, pad, snapshot, sats, t0, stable=True, labels=None):
    """layout() with or without satellites (NF021), with or without the stability start."""
    edges = [_copy_edge(e) for e in edges]
    linked = {e.u for e in edges} | {e.v for e in edges}
    alone = [i for i in items if i not in linked and not i.is_point]
    if len(alone) == len(items):
        alone = []
    L = _Layout([i for i in items if i not in alone], edges, mode)
    L.use_sats = sats
    L.label_w = dict(labels or {})
    L.rank()
    L.add_dummies()
    seeds = range(P.SEEDS if mode == 'relayout' else 1)
    if P.SEED_ONLY is not None and mode == 'relayout':
        seeds = [P.SEED_ONLY]
    best, seed_costs, crossings = {}, [], None  # best per zone output mode: (cost, Cand, seed)
    for seed in seeds:
        rng = random.Random(seed) if seed else None
        cands = L.order(rng)
        if crossings is None:
            crossings = L.crossings_after_order
        if 'force' in P.ORDERS and mode == 'relayout':
            force = L.force_cands(cands[0], rng)
            cands = (cands if 'cross' in P.ORDERS else []) + force
        if mode == 'relayout' and L._zone_pair() is not None:  # a zone: each way to place its output
            cands = [c._replace(zone=z) for c in cands for z in P.ZONE_OUT]
        # the cheapest start with a level zone output and the cheapest with a free one ('median'
        # or 'mean', whichever starts cheaper; one group outside zones): each is searched on its
        # own, since the orders that suit one zone output height rarely suit another
        first = {}
        for c in cands:
            cost = L._evaluate(c)
            if snapshot and not first:
                snapshot(f'seed {seed}: order', snapshot_state(L))
            g = _group(c.zone)
            if g not in first or cost < first[g][0] - 1e-9:
                first[g] = (cost, c)
        costs = []
        state = rng.getstate() if rng else None
        for z in sorted(first, key=_zone_rank):
            if rng:
                rng.setstate(state)  # each mode's search as if it were the only one
            cost, cand = L.improve(first[z][1], first[z][0], P.SEARCH_SEED, rng)
            costs.append(cost)
            if z not in best or cost < best[z][0] - 1e-9:
                best[z] = (cost, cand, seed)
        seed_costs.append(round(min(costs), 3))
        if snapshot:
            snapshot(f'seed {seed}', snapshot_state(L))
    # the best layout of each zone output mode gets the full search and the slide (a free zone
    # output can slide, a level one cannot, so the modes are compared after both)
    finals = {}
    for z in sorted(best, key=_zone_rank):
        cost, cand = L.improve(best[z][1], best[z][0], P.SEARCH)
        finals[z] = (L.slide(), cand, best[z][2])
    last = z
    if mode == 'relayout' and P.STABLE is not None and stable:
        # stability: the layout of the current order (each column sorted by where its nodes and
        # wires are now) replaces the fresh one when it costs at most STABLE more (0: when it is
        # as good or better), so a small edit does not reshuffle a formatted tree
        cur = {}
        for c in L.current_cands():
            cost = L._evaluate(c)
            g = _group(c.zone)
            if g not in cur or cost < cur[g][0] - 1e-9:
                cur[g] = (cost, c)
        for z, (cost, c) in sorted(cur.items(), key=lambda kv: _zone_rank(kv[0])):
            if z not in finals:
                continue
            L._evaluate(finals[z][1])
            L.slide()
            if _as_now(L):
                continue  # the fresh layout is the current one: a formatted tree stays as it is
            # no search from it: the same order gives the same layout again, so a layout kept
            # this way is kept by the next format too
            L._evaluate(c)
            cost = L.slide()
            if cost <= finals[z][0] + P.STABLE * max(1.0, abs(finals[z][0])) + 1e-9:
                finals[z] = (cost, c, 'current')
        last = None  # realize() lays out the chosen candidate again
    if snapshot:
        snapshot('search', snapshot_state(L))
        snapshot('slide', snapshot_state(L))

    def realize(z):
        """The finished Result of zone output mode z (its items moved to that layout)."""
        nonlocal last
        if z != last:
            L.items = [i for i in L.items if i not in alone]
            L._evaluate(finals[z][1])  # deterministic: the same layout again
            L.slide()
            last = z
        L.items = [i for i in L.items if i not in alone]
        L.shelf(alone)
        res = L.finish(pad)
        res.seed_costs, res.best_seed, res.cost = seed_costs, finals[z][2], round(finals[z][0], 3)
        res.placer = f"{L.placer}/{L.origin}" + (f"/{L.zone}" if L._zone_pair() is not None else "")
        res.cost_parts = dict(L.cost_parts)
        res.zone_mode = z
        res.realize = realize
        res.seconds = round(time.perf_counter() - t0, 3)
        # the other groups, cheapest first, for the parent to compare (layout.py): their costs
        res.alts = sorted(((round(c, 3), m) for m, (c, _, _) in finals.items()), key=lambda a: (a[0], _zone_rank(a[1])))
        return res
    win = min(finals, key=lambda z: (finals[z][0], _zone_rank(z)))
    return realize(win)


def _as_now(L):
    """True if the layout of L puts its nodes where they are now, up to a translation (the
    blocks of frames and zones are checked by their own containers)."""
    its = [i for i in L.items if i.kind == 'node' and i.ox is not None and i.oy is not None]
    if not its:
        return False
    dx, dy = its[0].x - its[0].ox, its[0].y - its[0].oy
    return all(abs(i.x - i.ox - dx) <= 1.0 and abs(i.y - i.oy - dy) <= 1.0 for i in its)


def _copy_edge(e):
    """A copy of an edge (each layout run changes the input keys of its edges)."""
    c = Edge(e.u, e.uk, e.v, e.vk, e.tag, e.geo)
    c.route = getattr(e, 'route', None)
    return c


def _group(z):
    """The search group of a zone output mode: 'level', or 'free' for the others."""
    return 'level' if z == 'level' else 'free'


def _zone_rank(g):
    """Sort key of a search group: 'level' first."""
    return 0 if g == 'level' else 1


def snapshot_state(L):
    """Plain data of a layout in progress (for animations): items as [id, kind, x, y, w, h] in
    the container's own coordinates, edges as [source id, target id], and the cost parts."""
    return {"items": [[repr(i.id), i.kind, round(i.x, 1), round(i.y, 1), i.w, i.h] for i in L.items],
            "edges": [[repr(e.u.id), repr(e.v.id)] for e in L.edges],
            "cost": dict(getattr(L, 'cost_parts', {}))}


class _Layout(RankingMixin, OrderingMixin, ForceMixin, PlacementMixin, RelaxMixin, ColumnsMixin, CostMixin,
              SearchMixin, LayoutBase):
    """The layout of one container, built step by step (see layout())."""

    def __init__(self, items, edges, mode):
        """Items and edges of the container; mode is 'relayout' or 'keep'."""
        self.items = list(items)
        self.edges = list(edges)
        self.mode = mode

    def current_cands(self):
        """Candidates with the order the items have now (graph.Cand, one per placement method
        and zone output mode): each column sorted by the items' current heights; a lane takes
        the height where the wire it carries crosses the column now (old route, model.py)."""
        layers = [[] for _ in range(self.R + 1)]
        for i in self.items:
            layers[i.rank].append(i)
        colx = []
        for layer in layers:
            xs = [i.ox + i.w / 2 for i in layer if not i.is_point and i.ox is not None]
            colx.append(sum(xs) / len(xs) if xs else None)
        known = [k for k, x in enumerate(colx) if x is not None]
        if not known:
            return []
        for k in range(len(colx)):  # columns of lanes only: between their neighbours
            if colx[k] is None:
                lo = max((j for j in known if j < k), default=None)
                hi = min((j for j in known if j > k), default=None)
                if lo is None:
                    colx[k] = colx[hi] - 200.0 * (hi - k)
                elif hi is None:
                    colx[k] = colx[lo] + 200.0 * (k - lo)
                else:
                    colx[k] = colx[lo] + (colx[hi] - colx[lo]) * (k - lo) / (hi - lo)
        oy = {}
        for i in self.items:
            if not i.is_point:
                oy[i] = (i.oy if i.oy is not None else 0.0) + (i.h / 2 if i.kind == 'compound' else 0.0)
                continue
            rs = [r for r in getattr(i, 'routes', []) if r]
            if i.kind in ('pin_in', 'pin_out'):
                es = self.succ_edges[i] if i.kind == 'pin_in' else self.pred_edges[i]
                rs = [e.route for e in es if getattr(e, 'route', None)]
                x = colx[0] - 100.0 if i.kind == 'pin_in' else colx[-1] + 100.0
            else:
                x = colx[i.rank]
            oy[i] = _sample(rs[0], x) if rs else 0.0
        for layer in layers:
            layer.sort(key=lambda i: (oy[i], _name_key(i)))
        layers = self._zone_first(layers)
        comm = [tuple(e.vk0 for e in es) for _, _, es in self.comm_items]
        zones = P.ZONE_OUT if self._zone_pair() is not None else ('level',)
        return [Cand(layers, comm, frozenset(), placer, 'current', z) for placer in P.PLACERS for z in zones]

    def out_pt(self, i, key):
        """Point where a link leaves item i (a port: the container's left edge)."""
        if i.kind == 'pin_in':
            return (self.left_edge, i.y)
        if i.is_point:
            return (i.x, i.y)
        dx, dy = i.outs.get(key, (i.w, 0))
        return (i.x + dx, i.y + dy)

    def in_pt(self, i, key):
        """Point where a link enters item i (a port: the container's right edge)."""
        if i.kind == 'pin_out':
            return (self.right_edge, i.y)
        if i.is_point:
            return (i.x, i.y)
        dx, dy = i.ins.get(key, (0, 0))
        return (i.x + dx, i.y + dy)

    def finish(self, pad):
        """The result of the container: item positions, route segments (source tag, start, end,
        destination key) and the bounding box with `pad` around it."""
        reals = [i for i in self.items if not i.is_point]
        pts = [i for i in self.items if i.is_point]
        xs = [i.x for i in reals] + [i.x + i.w for i in reals] + [i.x for i in pts if i.kind in ('dummy', 'label')]
        ys = [i.y for i in reals] + [i.y + i.h for i in reals] + [i.y for i in pts]
        for g in self.track_x:
            xs += list(g.values())
        minx, maxx = (min(xs), max(xs)) if xs else (0.0, 0.0)
        miny, maxy = (min(ys), max(ys)) if ys else (0.0, 0.0)
        miny = snap_down(miny)
        minx = snap_down(minx)
        pl, pt, pr, pb = (snap_up(p) for p in pad)
        self.left_edge = minx - pl
        self.right_edge = maxx + pr
        segs = []
        for e in self.edges:
            p, q = self.out_pt(e.u, e.uk), self.in_pt(e.v, e.vk)
            dst = None if e.v.kind in ('dummy', 'pin_in', 'pin_out') else (e.v.id, e.vk)
            k = e.u.rank
            t = self._turn_y(e)
            if t is not None:
                xc = self.track_x[k][e.tag]
                segs.append((e.tag, p, (xc, p[1]), None))
                segs.append((e.tag, (xc, p[1]), (xc, t), None))
                segs.append((e.tag, (xc, t), q, dst))
            else:
                segs.append((e.tag, p, q, dst))
        res = Result()
        res.items = self.items
        res.segments = segs
        res.origin = (minx - pl, miny - pt)
        res.w = (maxx + pr) - (minx - pl)
        res.h = (maxy + pb) - (miny - pt)
        res.ranks = self.R + 1
        res.crossings = self.crossings_after_order
        res.aligned = len(self.aligned)
        res.swapped = list(getattr(self, 'swapped', []))
        return res


def _sample(poly, x):
    """Height of polyline `poly` (a wire as it was drawn) where it first reaches x."""
    for a, b in zip(poly, poly[1:]):
        if min(a[0], b[0]) - 1e-6 <= x <= max(a[0], b[0]) + 1e-6:
            if abs(b[0] - a[0]) < 1e-6:
                return a[1]
            return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
    return poly[0][1] if x < poly[0][0] else poly[-1][1]
