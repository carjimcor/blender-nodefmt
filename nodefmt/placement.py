# SPDX-License-Identifier: GPL-3.0-or-later
"""Placement: vertical positions of the items (blocks of straight links, compaction).

assign_y() dispatches on the placement method: 'relax' is in relax.py; 'blocks' (blocks_y) merges
the items joined by straight links into blocks, then _compact() positions the blocks. 'balanced'
(only with NF022) is 'blocks' without the pull to a common top line.
"""
import math

from . import params as P
from .graph import snap_up, snap_down


class PlacementMixin:
    """Blocks of aligned links, then a compaction that solves separation constraints."""

    def assign_y(self):
        """Vertical positions of all items, by the current placement method."""
        if getattr(self, 'placer', 'blocks') == 'relax':
            self.relax_y()
        else:  # 'blocks' or 'balanced'
            self.blocks_y()

    def blocks_y(self):
        """Block placement: links are made straight in order of priority (geometry flow, main
        inputs, bundles of parallel links, lanes) by merging the items they join into blocks,
        as far as column order and a height limit allow; then the blocks are compacted."""
        items = self.items
        self.block = {i: i for i in items}       # union-find parent
        self.members = {i: {i: 0.0} for i in items}  # root -> {item: rel y}
        # flat lookups of the same, kept in step by _try_merge: item -> root, item -> rel y
        self._root = {i: i for i in items}
        self._rel = {i: 0.0 for i in items}
        self._hs = [i.h for i in self._rel]  # heights, in the order of _rel
        # neighbours in the columns (fixed while the blocks grow): (a, b, a.h, gap below a)
        self._pairs = [(a, b, a.h, self._gap(a, b)) for layer in self.layers for a, b in zip(layer, layer[1:])]
        # the block order constraints (_merge_cycle) as adjacency sets, kept in step by _try_merge
        self._bsucc = {i: set() for i in items}
        self._bpred = {i: set() for i in items}
        for a, b, _, _ in self._pairs:
            self._bsucc[a].add(b)
            self._bpred[b].add(a)
        cands = []
        prio = self._priorities()
        # a bundle: several links between the same two nodes that one offset makes all straight
        bundle = {}
        for e in self.edges:
            if not e.u.is_point and not e.v.is_point:
                k = (e.u, e.v, round(e.u.outs.get(e.uk, (0, 0))[1] - e.v.ins.get(e.vk, (0, 0))[1], 1))
                bundle[k] = bundle.get(k, 0) + 1
        for e in self.edges:
            if e.u.kind == 'dummy' and e.v.kind not in ('dummy', 'label') and not e.geo:
                continue  # the end of a long data lane: the node stays near its consumers, the lane taps in
            n = 1
            if not e.u.is_point and not e.v.is_point:
                n = bundle[(e.u, e.v, round(e.u.outs.get(e.uk, (0, 0))[1] - e.v.ins.get(e.vk, (0, 0))[1], 1))]
            p = 0 if n >= P.BUNDLE else prio[e]
            cands.append((p, -n, abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)), e))
        cands.sort(key=lambda c: (c[0], c[1], c[2]))
        cands = [(c[0], c[2], c[3]) for c in cands]
        self.height = self.base_height = self._height()
        if not self._zone_free():  # 'level': the zone output on the zone input's line
            self._level_zone()
        aligned_in = set()
        used_out = set()
        self.aligned = []
        by_pair = {}
        for p, _, e in cands:
            if e in self.banned:
                continue  # the search found the layout better with this link bent
            u, v = e.u, e.v
            if v in aligned_in or (u, e.uk) in used_out:
                continue
            ru, rv = self._find(u), self._find(v)
            if ru is rv:
                continue
            # alignments between the same two columns must not cross
            ok = True
            for f in by_pair.get(u.rank, []):
                a = (u.order, u.outs.get(e.uk, (0, 0))[1]) < (f.u.order, f.u.outs.get(f.uk, (0, 0))[1])
                b = (v.order, v.ins.get(e.vk, (0, 0))[1]) < (f.v.order, f.v.ins.get(f.vk, (0, 0))[1])
                if a != b:
                    ok = False
                    break
            if not ok:
                continue
            off = self.members[ru][u] + u.outs.get(e.uk, (0, 0))[1] - v.ins.get(e.vk, (0, 0))[1] - self.members[rv][v]
            cap = None if p == 0 else max(self.base_height * 1.3, self.base_height + 200)
            if not self._try_merge(ru, rv, off, P.ALIGN_LIMIT[p], cap):
                continue
            aligned_in.add(v)
            used_out.add((u, e.uk))
            by_pair.setdefault(u.rank, []).append(e)
            self.aligned.append(e)
        self.aligned_set = set(self.aligned)
        self._compact()
        # links the compaction made straight join their blocks, so the next round moves them together
        for _ in range(2):
            merged = False
            for e in self.edges:
                ru, rv = self._find(e.u), self._find(e.v)
                if ru is rv or e in self.banned:
                    continue
                if abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)) > P.EPS:
                    continue
                off = e.v.y - e.u.y + self.members[ru][e.u] - self.members[rv][e.v]
                if self._try_merge(ru, rv, off):
                    self.aligned.append(e)
                    merged = True
            if not merged:
                break
            self.aligned_set = set(self.aligned)
            self._compact()

    def _lead(self, k):
        """How many items head column k above a zone's content: ports above the zone input and
        the lanes of their wires (ordering.use)."""
        above = getattr(self, 'above', ())
        n = 0
        for i in self.layers[k]:
            if i not in above:
                break
            n += 1
        return n

    def _level_zone(self):
        """A zone's input and output node sit on one line (one block): the socket they share
        (same item, geometry first) is level, else their tops."""
        zp = self._zone_pair()
        if zp is not None:
            a, b, off = zp
            self._try_merge(self._find(a), self._find(b), off)

    def _priorities(self):
        """Link -> priority to be made straight (0 first): the geometry flow (main geometry input
        of a node that passes geometry on), other main inputs, links to an output port, links
        from lanes, the rest. A lane gets the priority of the best link it carries (at most 3)."""
        prio = {}
        for e in self.edges:
            v = e.v
            if v.kind in ('dummy', 'label'):
                continue
            if e.main and e.geo and (getattr(v, 'geo_out', False) or v.pin == 'last'):
                p = 0
            elif e.main and e.geo:
                p = 1
            elif e.main and not e.u.is_point:
                p = 2
            elif v.kind == 'pin_out':
                p = 3
            elif e.u.is_point:
                p = 4
            else:
                p = 5
            prio[e] = p
        for k in range(self.R, -1, -1):
            for d in self.layers[k] if hasattr(self, 'layers') else []:
                if d.kind not in ('dummy', 'label'):
                    continue
                best = min((prio[f] for f in self.succ_edges[d] if f in prio), default=3)
                for e in self.pred_edges[d]:
                    prio[e] = max(min(best, 3), 0) if best >= 3 else best
        return prio

    def _find(self, i):
        """Root of the block that holds item i."""
        return self._root[i]

    def _try_merge(self, ra, rb, off, limit=None, cap=None):
        """Merge block rb into ra with rel(rb item) = rel_rb + off; True if merged. Rejects
        overlaps, cycles, and merges that make the layout more than `limit` taller than now or
        taller than `cap`."""
        mb = self.members[rb]
        merged = dict(self.members[ra])
        for i, r in mb.items():
            merged[i] = r + off
        above = getattr(self, 'above', ())
        if above and len({i in above for i in merged}) > 1:
            return False  # a wire entering a zone above its input drops to its node: no block
        # items of one block in one column: consecutive in the order and far enough apart
        bycol = {}
        for i in merged:
            bycol.setdefault(i.rank, []).append(i)
        zin = self._zone_input()
        top_only = zin is not None and self._root[zin] in (ra, rb)
        if top_only and any(r < merged[zin] - 1e-6 for i, r in merged.items() if i not in above):
            return False  # a zone's content hangs below the zone input's top line
        for k, its in bycol.items():
            if top_only:  # what lines up with a zone input heads its column (after ports above it)
                lead = self._lead(k)
                if sorted(i.order for i in its) != list(range(lead, lead + len(its))):
                    return False
            if len(its) < 2:
                continue
            its.sort(key=lambda i: i.order)
            if its[-1].order - its[0].order != len(its) - 1:
                return False
            for a, b in zip(its, its[1:]):
                if merged[b] < merged[a] + a.h + self._gap(a, b) - 1e-6:
                    return False
        # the block graph must stay without a cycle
        if self._merge_cycle(ra, rb):
            return False
        # tentatively apply (the height is measured with rb's items in ra)
        root, rel = self._root, self._rel
        for i in mb:
            root[i] = ra
            rel[i] = merged[i]
        old_a = self.members[ra]
        self.members[ra] = merged
        del self.members[rb]
        h = self._height()
        if limit is not None and (h > self.height + limit or (cap is not None and h > cap)):
            self.members[ra], self.members[rb] = old_a, mb
            for i, r in mb.items():
                root[i] = rb
                rel[i] = r
            return False
        self.block[rb] = ra
        # the block graph: rb's edges become ra's (an edge between the two disappears)
        bsucc, bpred = self._bsucc, self._bpred
        for x in bsucc.pop(rb):
            bpred[x].discard(rb)
            if x is not ra:
                bpred[x].add(ra)
                bsucc[ra].add(x)
        for x in bpred.pop(rb):
            bsucc[x].discard(rb)
            if x is not ra:
                bsucc[x].add(ra)
                bpred[ra].add(x)
        self.height = h
        return True

    def _merge_cycle(self, ra, rb):
        """True if merging blocks ra and rb would make the block order constraints cyclic (a is
        above b if a holds an item right above one of b in a column). The graph is acyclic now,
        so the merge makes a cycle exactly when a path leads from one block to the other through
        a third block."""
        succ = self._bsucc
        for a, b in ((ra, rb), (rb, ra)):
            todo = [x for x in succ[a] if x is not b]
            seen = set(todo)
            while todo:
                x = todo.pop()
                for y in succ[x]:
                    if y is b:
                        return True
                    if y not in seen:
                        seen.add(y)
                        todo.append(y)
        return False

    def _height(self):
        """Height of the tightest stacking of the current blocks (longest path, top-packed)."""
        rel, root = self._rel, self._root
        # separation constraints between blocks: Y_b >= Y_a + c for each two neighbours in a
        # column (several between two blocks give the same longest path as their maximum)
        succ, indeg = {}, dict.fromkeys(self.members, 0)
        for a, b, ah, gap in self._pairs:
            ra, rb = root[a], root[b]
            if ra is not rb:
                c = rel[a] + ah + gap - rel[b]
                out = succ.get(ra)
                if out is None:
                    succ[ra] = [(rb, c)]
                else:
                    out.append((rb, c))
                indeg[rb] += 1
        Y = dict.fromkeys(self.members, 0.0)
        todo = [r for r, n in indeg.items() if n == 0]
        while todo:
            a = todo.pop()
            ya = Y[a]
            for b, c in succ.get(a, ()):
                if ya + c > Y[b]:
                    Y[b] = ya + c
                indeg[b] -= 1
                if indeg[b] == 0:
                    todo.append(b)
        tops = [Y[root[i]] + v for i, v in rel.items()]
        return max([t + h for t, h in zip(tops, self._hs)]) - min(tops)

    def _compact(self):
        """Vertical positions of the blocks: separation constraints from each column's order, then
        an iterative solution that pulls each block towards the heights that make its other links
        straight (weighted medians, VPSC-like merging of colliding blocks, coordinate descent),
        with a small pull to a common top line (gravity) unless the placement is 'balanced'."""
        roots = list(self.members)
        rel = {}
        for r in roots:
            for i, v in self.members[r].items():
                rel[i] = v
        self.rel = rel
        # anchor: a real item whose top goes on the grid
        anchor = {}
        for r in roots:
            reals = [i for i in self.members[r] if not i.is_point]
            if reals:
                # the grid phase that puts most of the block's nodes on the grid (frames and zones
                # weigh most: everything inside them is on the grid already)
                def phase(i):
                    """Grid phase of an item's relative height in its block."""
                    return round(rel[i] % P.GRID, 1) % P.GRID
                count = {}
                for i in reals:
                    count[phase(i)] = count.get(phase(i), 0) + (100 if i.kind == 'compound' else 1)
                a = max(reals, key=lambda i: (count[phase(i)], i.kind == 'compound', i.h, -i.rank))
                anchor[r] = rel[a]
            else:  # a lane: on the grid too
                anchor[r] = rel[next(iter(self.members[r]))]
        strict = {r for r in roots if any(i.kind == 'compound' for i in self.members[r])}
        if not P.SNAP:  # the grid does not matter: blocks go wherever their links want them
            anchor, strict = {}, set()
        # constraints between blocks: Y_b >= Y_a + c
        cons = {}
        for layer in self.layers:
            for a, b in zip(layer, layer[1:]):
                ra, rb = self._find(a), self._find(b)
                if ra is rb:
                    continue
                c = rel[a] + a.h + self._gap(a, b) - rel[b]
                cons[(ra, rb)] = max(cons.get((ra, rb), -1e18), c)
        # a zone's input node is its top-left corner: the zone's content hangs below its top line
        zin = self._zone_input()
        if zin is not None:
            Z = self._find(zin)
            rev = {}
            for (a, b) in cons:
                rev.setdefault(b, []).append(a)
            anc, todo = set(), [Z]
            while todo:
                x = todo.pop()
                for a in rev.get(x, ()):
                    if a not in anc:
                        anc.add(a)
                        todo.append(a)
            above = getattr(self, 'above', set())
            for r in roots:
                if r is Z or r in anc or all(i in above for i in self.members[r]):
                    continue
                c = rel[zin] - min(rel[i] for i in self.members[r])
                cons[(Z, r)] = max(cons.get((Z, r), -1e18), c)
        # anchored neighbours keep a whole number of grid steps between their tops
        for (a, b), c in list(cons.items()):
            if a in anchor and b in anchor:
                cons[(a, b)] = snap_up(c + anchor[b] - anchor[a] - 1e-6) - anchor[b] + anchor[a]
        preds = {r: [] for r in roots}
        succs = {r: [] for r in roots}
        for (a, b), c in cons.items():
            preds[b].append((a, c))
            succs[a].append((b, c))
        indeg = {r: len(preds[r]) for r in roots}
        topo = [r for r in roots if indeg[r] == 0]
        k = 0
        while k < len(topo):
            for b, _ in succs[topo[k]]:
                indeg[b] -= 1
                if indeg[b] == 0:
                    topo.append(b)
            k += 1

        def snap(r, y, up=True):
            """Grid-snapped position of block r (only with P.SNAP), rounding up or down."""
            if r not in anchor:
                return y
            t = y + anchor[r]
            t = snap_up(t - 1e-6) if up else snap_down(t + 1e-6)
            return t - anchor[r]

        def snap_near(r, y):
            """Grid-snapped position of block r to the nearest step (only with P.SNAP)."""
            if r not in anchor:
                return y
            return round((y + anchor[r]) / P.GRID) * P.GRID - anchor[r]

        def feasible(Y):
            """Push blocks down until every separation constraint holds."""
            for r in topo:
                lo = max([Y[a] + c for a, c in preds[r]], default=None)
                if lo is not None and Y[r] < lo - 1e-6:
                    Y[r] = snap(r, lo)
            return Y

        Y = {}
        for r in topo:
            lo = max([Y[a] + c for a, c in preds[r]], default=None)
            if lo is None:
                lo = min((i.y - rel[i] for i in self.members[r]), default=0.0) if self.mode == 'keep' else 0.0
            Y[r] = snap(r, lo)
        # attraction targets: non-aligned edges between blocks
        pulls = {r: [] for r in roots}
        for e in self.edges:
            if e in self.aligned_set:
                continue
            ru, rv = self._find(e.u), self._find(e.v)
            if ru is rv:
                continue
            w = 8.0 if e.main else (3.0 if e.geo else 1.0)
            if e.u.is_point or e.v.is_point:
                w *= 1.5
            if e.u.is_point and not e.geo and e.v.kind != 'dummy':
                w = 0.4  # a node fed by a long lane sits near its consumers; the lane taps up or down
            su = rel[e.u] + e.u.outs.get(e.uk, (0, 0))[1]
            sv = rel[e.v] + e.v.ins.get(e.vk, (0, 0))[1]
            # a source node (nothing linked in) stays close to the socket it feeds
            slope = P.SRC_SLOPE if getattr(e.u, 'src', False) else P.BEND_SLOPE
            pulls[rv].append((ru, su - sv, w, slope))   # Y_rv = Y_ru + su - sv makes it straight
            pulls[ru].append((rv, sv - su, w, slope))
        # a zone's input and output like to be level (a soft pull: a free output follows its links)
        zp = self._zone_pair()
        zout_root = None
        if zp is not None:
            a, b, off = zp
            ra, rb = self._find(a), self._find(b)
            if ra is not rb:
                zout_root = rb
                pulls[rb].append((ra, rel[a] + off - rel[b], P.ZONE_LEVEL, P.BEND_SLOPE))
                pulls[ra].append((rb, rel[b] - off - rel[a], P.ZONE_LEVEL, P.BEND_SLOPE))
        firsts = [i for i in self.items if i.pin == 'first' and i.kind == 'node']
        lasts = [i for i in self.items if i.pin == 'last' and i.kind == 'node']
        if zp is None and len(firsts) == 1 and len(lasts) == 1:
            a, b = firsts[0], lasts[0]
            ra, rb = self._find(a), self._find(b)
            if ra is not rb:
                pulls[rb].append((ra, rel[a] - rel[b], 6.0, P.BEND_SLOPE))
                pulls[ra].append((rb, rel[b] - rel[a], 6.0, P.BEND_SLOPE))
        if self.mode == 'keep':
            for r in roots:
                for i in self.members[r]:
                    if not i.is_point and i.oy is not None:
                        pulls[r].append((None, i.oy - rel[i], 0.5, None))
        elif getattr(self, 'placer', 'blocks') != 'balanced':
            # gravity: every block drifts up to a common top line unless its links hold it
            # ('balanced', NF022, has none: a converging tree takes a ">" shape)
            top = min(Y.values(), default=0.0)
            for r in roots:
                if r is zout_root:
                    continue  # a free zone output follows its inputs, not the top line
                n = sum(1 for i in self.members[r] if not i.is_point and not getattr(i, 'src', False))
                if n:
                    pulls[r].append((None, top - min(rel[i] for i in self.members[r]), P.GRAVITY * n, None))

        # tidy rows: a block likes a node's top or bottom level with a node in the next column
        edges_of = {r: [] for r in roots}
        for r in (roots if P.ALIGN_BONUS else ()):
            for i in self.members[r]:
                if i.is_point:
                    continue
                for k in (i.rank - 1, i.rank + 1):
                    if 0 <= k <= self.R:
                        for j in self.layers[k]:
                            if not j.is_point and self._find(j) is not r:
                                edges_of[r].append((rel[i], i.h, self._find(j), rel[j], j.h))

        def tidy(r, c, Y):
            """Bonus for a block level with a node in the next column (ALIGN_BONUS, off by default)."""
            for ri, hi_, rj, rlj, hj in edges_of[r]:
                tj = Y[rj] + rlj
                if abs(c + ri - tj) < 0.5 or abs(c + ri + hi_ - tj - hj) < 0.5:
                    return -P.ALIGN_BONUS
            return 0.0

        def median(vals):
            """Weighted median of [(value, weight)]."""
            return median_sorted(sorted(vals))

        def median_sorted(vals):
            """median() of a list that is sorted already."""
            half = sum([w for _, w in vals]) / 2
            acc = 0.0
            for v, w in vals:
                acc += w
                if acc >= half - 1e-9:
                    return v
            return vals[-1][0]

        def wants(r, Y):
            """The heights block r's pulls want, as (value, weight, slope)."""
            return [((Y[o] + d) if o is not None else d, w, sl) for o, d, w, sl in pulls[r]]

        def pen(dist, w, slope):
            """Cost of a pull that is `dist` away: linear without a slope, else a fixed price for
            a bent link (two reroutes, whatever its drop) plus the slope."""
            if slope is None:
                return w * dist
            return 0.0 if dist <= P.EPS else w * (P.BEND + slope * dist)

        EPS, BEND = P.EPS, P.BEND

        def cost(Y):
            """Total cost of the pulls for block positions Y."""
            return sum([pen(abs(((Y[o] + d) if o is not None else d) - Y[r]), w, sl)
                        for r in roots for o, d, w, sl in pulls[r]]) + sum(tidy(r, Y[r], Y) for r in roots)

        def satisfy(Y):
            """Each block at the median of what its links want; where two blocks collide they
            merge and move together to the median of both (separation constraints, VPSC style)."""
            # a cluster of blocks: [offsets {block: offset}, wanted (value, weight), position]
            cl = {}
            for r in topo:
                vals = sorted([((Y[o] + d) if o is not None else d, w) for o, d, w, _ in pulls[r]])
                C = [{r: 0.0}, vals, snap_near(r, median_sorted(vals)) if vals else Y[r]]
                cl[r] = C
                while True:
                    worst = None
                    wv = 1e-6  # the worst violation so far (the first of equal ones wins)
                    pos = C[2]
                    for m, off in C[0].items():
                        here = pos + off
                        for a, c in preds[m]:
                            Ca = cl.get(a)
                            if Ca is None or Ca is C:
                                continue
                            viol = (Ca[2] + Ca[0][a] + c) - here
                            if viol > wv:
                                wv = viol
                                worst = (viol, Ca, a, m, c)
                    if worst is None:
                        break
                    _, Ca, a, m, c = worst
                    offs = Ca[0]
                    shift = offs[a] + c - C[0][m]
                    for x, off in C[0].items():
                        offs[x] = off + shift
                        cl[x] = Ca
                    # the wanted heights stay sorted: two sorted runs sort in about linear time
                    Ca[1] += [(v - shift, w) for v, w in C[1]]
                    Ca[1].sort()
                    if Ca[1]:
                        ref = next((x for x in offs if x in anchor), None) if anchor else None
                        p = median_sorted(Ca[1])
                        if ref is not None:
                            p = snap_near(ref, p + offs[ref]) - offs[ref]
                        Ca[2] = p
                    C = Ca
            return feasible({r: cl[r][2] + cl[r][0][r] for r in roots})

        # block -> the blocks whose best position (local) reads its position: through pulls,
        # separation constraints and rows (ALIGN_BONUS)
        deps = {r: set() for r in roots}
        for r in roots:
            for o, _, _, _ in pulls[r]:
                if o is not None:
                    deps[o].add(r)
            for x, _ in preds[r] + succs[r]:
                deps[x].add(r)
            for _, _, rj, _, _ in edges_of[r]:
                deps[rj].add(r)

        def local(Y, rounds=10):
            """Coordinate descent: each block in turn to its best position within its constraints.
            A block is looked at again only when something it reads has moved (with the same
            inputs it would choose the same place)."""
            dirty = set(roots)
            for it in range(rounds):
                changed = False
                for r in (topo if it % 2 == 0 else reversed(topo)):
                    if r not in dirty:
                        continue
                    dirty.discard(r)
                    pr = pulls[r]
                    if not pr:
                        continue
                    ws = [((Y[o] + d) if o is not None else d, w, sl) for o, d, w, sl in pr]
                    want = median([(v, w) for v, w, _ in ws])
                    lo = max([Y[a] + c for a, c in preds[r]], default=-1e18)
                    hi = min([Y[b] - c for b, c in succs[r]], default=1e18)
                    if lo > hi:
                        continue
                    on_grid = r in anchor
                    eo = edges_of[r]

                    def score(c):
                        """Cost of block r at height c (its pulls and the grid price)."""
                        off = on_grid and abs(snap_near(r, c) - c) > 1e-6
                        if off and r in strict:
                            return 1e18  # a frame or zone stays on the grid
                        # pen() inlined: the same terms, summed in the same order
                        return (sum([w * abs(v - c) if sl is None else
                                     (0.0 if abs(v - c) <= EPS else w * (BEND + sl * abs(v - c)))
                                     for v, w, sl in ws]) + (P.GRID_PRICE if off else 0.0)
                                + (tidy(r, c, Y) if eo else 0.0))

                    # candidates: the median, every position that makes one link straight, grid
                    # steps, tops and bottoms level with the next columns
                    opts = [c for c in (Y[rj] + rlj - ri for ri, _, rj, rlj, _ in eo)
                            if lo - 1e-6 <= c <= hi + 1e-6]
                    opts += [c for c in (Y[rj] + rlj + hj - ri - hi_ for ri, hi_, rj, rlj, hj in eo)
                             if lo - 1e-6 <= c <= hi + 1e-6]
                    for v in [want] + [v for v, _, sl in ws if sl is not None]:
                        t = min(max(v, lo), hi)
                        opts.append(t)
                        if on_grid:
                            opts += [c for c in (snap(r, t, False), snap(r, t, True)) if lo - 1e-6 <= c <= hi + 1e-6]
                    # the first cheapest option, as min(opts, key=score), scoring each value once
                    t, st = opts[0], score(opts[0])
                    done = {t: st}
                    for c in opts[1:]:
                        if c in done:
                            continue
                        sc = done[c] = score(c)
                        if sc < st:
                            t, st = c, sc
                    yr = Y[r]
                    if abs(t - yr) > 1e-6 and st < (done[yr] if yr in done else score(yr)) - 1e-6:
                        Y[r] = t
                        changed = True
                        dirty |= deps[r]
                if not changed:
                    break
            return Y

        Y = local(Y)
        best = (cost(Y), dict(Y))
        stale = 0
        for it in range(15):
            Y = local(satisfy(Y))
            c = cost(Y)
            if c < best[0] - 1e-6:
                best = (c, dict(Y))
                stale = 0
            else:
                stale += 1
                if stale >= 3:
                    break
        Y = best[1]
        self.compact_cost = best[0]
        if zout_root is not None and getattr(self, 'zone', 'level') == 'mean' and pulls[zout_root]:
            # 'mean': the free zone output block at the weighted mean of what its links want
            ws = wants(zout_root, Y)
            t = sum(v * w for v, w, _ in ws) / sum(w for _, w, _ in ws)
            lo = max([Y[a] + c for a, c in preds[zout_root]], default=-1e18)
            hi = min([Y[b] - c for b, c in succs[zout_root]], default=1e18)
            if lo <= hi:
                Y[zout_root] = min(max(t, lo), hi)
        for r in roots:
            y = math.floor(Y[r] + 0.5)  # whole units: Blender rounds node locations
            for i, v in self.members[r].items():
                i.y = y + v
