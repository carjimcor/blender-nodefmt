# SPDX-License-Identifier: GPL-3.0-or-later
"""Ranking: columns (layers) for the items of one container, and lanes (dummies) for long links."""

from . import params as P
from .graph import CycleError, Edge, Item, _name


class RankingMixin:
    """Longest-path layering with a zone input first and the Group Output or zone output last."""

    def _topo(self, items, edges):
        """Items in a topological order (ties by name, or by x in keep mode); raises CycleError."""
        indeg = {i: 0 for i in items}
        succ = {i: [] for i in items}
        for e in edges:
            indeg[e.v] += 1
            succ[e.u].append(e.v)
        order = [i for i in items if indeg[i] == 0]
        order.sort(key=(lambda i: i.ox if i.ox is not None else 0) if self.mode == "keep" else _name)
        k = 0
        while k < len(order):
            u = order[k]
            k += 1
            for v in succ[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    order.append(v)
        if len(order) != len(items):
            raise CycleError([i for i in items if indeg[i] > 0])
        return order

    def rank(self):
        """Set i.rank and i.sat of every item, and self.R. A big block (a zone or frame of several
        columns) gets a column of its own: nodes that would share it are kept to its right."""
        sats = self._satellites()
        for i in self.items:
            i.sat = i in sats
        extra = []
        for _ in range(8):
            self._rank(self.edges + extra)
            add = []
            out = {e.u for e in self.edges}
            for b in self.items:
                # a big block with no links out (a side branch) may share its column, and so may a
                # satellite (NF021): it sits above or below the others and reaches to the left
                if getattr(b, "big", False) and not b.sat and (b in out or not P.OVERHANG):
                    for i in self.items:
                        if (
                            i is not b
                            and i.rank == b.rank
                            and not i.is_point
                            and not getattr(i, "big", False)
                            and not i.sat
                            and not self._reaches(i, b, self.edges + extra)
                        ):
                            add.append(Edge(b, None, i, None, None))
            if not add:
                return
            extra += add

    def _satellites(self):
        """Satellites (NF021): big blocks (frames or zones of several columns) with nothing linked
        into them, such as a frame that starts from its own Group Input. Each sits at the top or
        bottom of the column right before its consumer and reaches left over the earlier columns
        (columns.py), so its output wire is short instead of crossing the whole tree."""
        if not P.SATELLITES or self.mode == "keep" or not getattr(self, "use_sats", True):
            return set()
        fed = {e.v for e in self.edges}
        feeds = {e.u for e in self.edges}
        return {
            b
            for b in self.items
            if b.kind == "compound" and getattr(b, "big", False) and b.pin is None and b not in fed and b in feeds
        }

    @staticmethod
    def _reaches(a, b, edges):
        """True if item a reaches item b along edges."""
        succ = {}
        for e in edges:
            succ.setdefault(e.u, []).append(e.v)
        seen, todo = {a}, [a]
        while todo:
            v = todo.pop()
            if v is b:
                return True
            for w in succ.get(v, ()):
                if w not in seen:
                    seen.add(w)
                    todo.append(w)
        return False

    def _rank(self, edges):
        """Longest-path ranks: sources as late as their consumers allow, pins first or last; empty
        ranks are removed. In keep mode, columns come from the original x positions."""
        items = self.items
        topo = self._topo(items, edges)
        preds = {i: [] for i in items}
        succs = {i: [] for i in items}
        for e in edges:
            preds[e.v].append(e.u)
            succs[e.u].append(e.v)
        r = {}
        if self.mode == "keep":
            real = sorted((i for i in items if i.ox is not None), key=lambda i: i.ox)
            col, start, c = {}, None, -1
            for i in real:
                if start is None or i.ox - start > 70:
                    c += 1
                    start = i.ox
                col[i] = c
            first = any(i.pin == "first" for i in items)
            for i in topo:
                if i.pin == "first":
                    r[i] = 0
                    continue
                base = col.get(i, 0) + (1 if first else 0)
                r[i] = max([base] + [r[p] + 1 for p in preds[i]])
        else:
            for i in topo:
                r[i] = 0 if i.pin == "first" else max([0] + [r[p] + 1 for p in preds[i]])
            R = max(r.values(), default=0)
            for i in reversed(topo):
                if i.pin == "first":
                    continue
                if i.pin == "last":
                    r[i] = R
                elif succs[i]:
                    r[i] = min(r[s] for s in succs[i]) - 1
        R = max(r.values(), default=0)
        for i in items:
            if i.pin == "last":
                r[i] = R
        # pinning the last items may break a constraint before them: re-check
        for i in topo:
            for p in preds[i]:
                if r[i] <= r[p]:
                    r[i] = r[p] + 1
        R = max(r.values(), default=0)
        for i in items:
            if i.pin == "last":
                r[i] = R
        # the pins of a part of the tree (part.py) take columns of their own: before and after
        # everything else, even nodes with no links inside the part
        own = [i for i in items if getattr(i, "own_column", False)]
        if own:
            rest = [i for i in items if not getattr(i, "own_column", False)]
            if any(i.pin == "first" for i in own):
                for i in rest:
                    r[i] += 1
            R = max((r[i] for i in rest), default=0)
            for i in own:
                r[i] = 0 if i.pin == "first" else R + 1
        # compress empty ranks
        used = sorted(set(r.values()))
        remap = {v: k for k, v in enumerate(used)}
        for i in items:
            i.rank = remap[r[i]]
        self.R = len(used) - 1 if used else 0

    def add_dummies(self):
        """Long links (spanning more than one gap) get one dummy per crossed column, shared by
        all links from the same source socket (a bus with taps)."""
        groups = {}
        for e in self.edges:
            groups.setdefault((e.u, e.uk), []).append(e)
        new_edges = []
        for (u, uk), es in groups.items():
            far = [e for e in es if e.v.rank > u.rank + 1]
            new_edges += [e for e in es if e.v.rank <= u.rank + 1]
            if not far:
                continue
            last = max(e.v.rank for e in far)
            prev, pk = u, uk
            bus = {}
            for k in range(u.rank + 1, last):
                d = Item(("dummy", es[0].tag, k), "dummy", ins={"in": (0, 0)}, outs={"out": (0, 0)})
                d.rank = k
                d.tag = es[0].tag
                d.oy = None
                # where the wires it carries ran before (stability: engine.current_cands)
                d.routes = [getattr(e, "route", None) for e in sorted(far, key=lambda e: repr(e.vk)) if e.v.rank > k]
                self.items.append(d)
                new_edges.append(Edge(prev, pk, d, "in", es[0].tag, es[0].geo))
                bus[k] = d
                prev, pk = d, "out"
            for e in far:
                new_edges.append(Edge(bus[e.v.rank - 1], "out", e.v, e.vk, e.tag, e.geo))
        for e in new_edges:
            if e.v.rank <= e.u.rank:
                raise ValueError(f"backward edge {e}")
        self.edges = new_edges
        self.pred_edges = {i: [] for i in self.items}
        self.succ_edges = {i: [] for i in self.items}
        for e in self.edges:
            self.pred_edges[e.v].append(e)
            self.succ_edges[e.u].append(e)
