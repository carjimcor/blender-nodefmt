# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordering: the vertical order of the items in each column (crossing reduction)."""
from . import params as P
from .graph import Cand, _name


class OrderingMixin:
    """Barycenter sweeps, neighbour transposition and commutative input swaps."""

    def _place(self, layer, desired):
        """Provisional y: each item at its desired top, pushed down to avoid the one above."""
        prev = None
        for i in layer:
            y = desired.get(i, i.y)
            if prev is not None:
                y = max(y, prev.y + prev.h + self._gap(prev, i))
            i.y = y
            prev = i

    def _crossings(self):
        """Crossings between consecutive columns, links compared by socket heights."""
        total = 0
        for k in range(self.R):
            es = [e for i in self.layers[k] for e in self.succ_edges[i]]
            pts = [(self._sock_y(e.u, e.uk, True), self._sock_y(e.v, e.vk, False)) for e in es]
            for a in range(len(pts)):
                for b in range(a + 1, len(pts)):
                    (p1, q1), (p2, q2) = pts[a], pts[b]
                    if (p1 - p2) * (q1 - q2) < -1e-6:
                        total += 1
        return total

    def order(self, rng=None):
        """Crossing reduction. Returns the P.CANDIDATES orders with the fewest crossings (counted
        between sockets), each with every placement method in P.PLACERS, as graph.Cand.

        Initial order: from the last column back, each item follows the sockets it feeds; then
        barycenter sweeps down and up (weighted towards main inputs), neighbour transposition and
        commutative input swaps. With a random generator (seeds other than 0) the initial order is
        jittered and the number and direction of sweeps vary."""
        layers = [[] for _ in range(self.R + 1)]
        for i in self.items:
            layers[i.rank].append(i)
        self.layers = layers
        if self.mode == 'keep':
            # initial order: original positions; dummies and ports follow their source socket
            for k, layer in enumerate(layers):
                for i in layer:
                    if i.oy is None:
                        i.oy = self._guess_oy(i)
                layer.sort(key=lambda i: i.oy)
                self._place(layer, {i: i.oy for i in layer})
        else:
            # initial order from the graph only (so formatting twice gives the same result):
            # from the last column back, each item follows the sockets it feeds
            for k in range(self.R, -1, -1):
                layer = layers[k]
                if k < self.R:
                    pos = {i: n for n, i in enumerate(layers[k + 1])}

                    def key(i):
                        """Initial sort key of an item in its column."""
                        ks = [pos[e.v] + e.v.ins.get(e.vk, (0, 0))[1] / 1e4 for e in self.succ_edges[i] if e.v in pos]
                        jit = rng.uniform(-P.JITTER, P.JITTER) if rng is not None else 0.0
                        return (sum(ks) / len(ks) + jit if ks else 1e9, _name(i))
                else:
                    def key(i):
                        """Initial sort key of an item in its column."""
                        return (0, _name(i))
                layer.sort(key=key)
                y = 0.0
                for i in layer:
                    i.y = y
                    y += i.h + self._gap(i, i)
        fixed_real = self.mode == 'keep'
        self.swapped = []
        for e in self.edges:  # vk0: the input as it is in the tree
            if not hasattr(e, 'vk0'):
                e.vk0 = e.vk
            e.vk = e.vk0
        comm = self._comm_units()
        self.comm_items = comm
        # every seed starts from the commutative inputs in a canonical state (by source), so the
        # result does not depend on how they are linked now and formatting twice changes nothing
        for _, pair, es in comm:
            for e, k in zip(sorted(es, key=lambda e: repr(e.tag)), pair):
                e.vk = k
        seen = {}

        def note():
            """Remember the current order (and its crossings) as a candidate."""
            c = self._crossings()
            key = (tuple(tuple(id(i) for i in l) for l in layers), tuple(self._comm_state(comm)))
            if key not in seen:
                seen[key] = (c, len(seen), [list(l) for l in layers], self._comm_state(comm))
        note()
        sweeps, first_down = (12, True) if rng is None else (rng.randint(8, 14), rng.random() < 0.7)
        for it in range(sweeps):
            down = (it % 2 == 0) == first_down
            rng = range(1, self.R + 1) if down else range(self.R - 1, -1, -1)
            for k in rng:
                layer = layers[k]
                desired = self._desired(layer, down)
                if fixed_real:
                    reals = [i for i in layer if not i.is_point]
                    pts = sorted((i for i in layer if i.is_point), key=lambda i: desired[i])
                    merged, ri = [], 0
                    for p in pts:
                        while ri < len(reals) and reals[ri].y + reals[ri].h / 2 <= desired[p]:
                            merged.append(reals[ri])
                            ri += 1
                        merged.append(p)
                    merged += reals[ri:]
                    layer[:] = merged
                else:
                    layer.sort(key=lambda i: desired[i])
                self._place(layer, desired)
            note()
            self._transpose(layers, fixed_real, down)
            self._swap_inputs(comm)
            note()
        ranked = sorted(seen.values(), key=lambda c: (c[0], c[1]))
        self.crossings_after_order = ranked[0][0]
        return [Cand(self._zone_first(c[2]), c[3], frozenset(), placer) for c in ranked[:P.CANDIDATES]
                for placer in P.PLACERS]

    def _zone_first(self, layers):
        """An order with the zone input (and output) heading their columns."""
        layers = [list(l) for l in layers]
        if self._zone_input() is not None:
            for layer in (layers[0], layers[-1]):
                for i in [i for i in layer if i.pin and i.kind == 'node' and getattr(i, 'zmatch', None) is not None]:
                    layer.remove(i)
                    layer.insert(0, i)
        return layers

    def use(self, cand):
        """Make a candidate order current: order indices, swapped inputs, provisional y."""
        layers, comm_state, self.banned, self.placer, self.origin, self.zone = cand
        self.layers = [list(l) for l in layers]
        zin = self._zone_input()
        self.above = set()
        if zin is not None:  # the zone input and output head their columns
            for layer in (self.layers[0], self.layers[-1]):
                for i in [i for i in layer if i.pin and i.kind == 'node' and getattr(i, 'zmatch', None) is not None]:
                    # ports put above the zone input by the search (NF033) stay there: a wire from
                    # outside may enter over the zone input instead of crossing its outputs
                    lead = 0
                    if layer is self.layers[0] and P.PORTS_ABOVE:
                        while lead < len(layer) and layer[lead].kind == 'pin_in':
                            lead += 1
                    layer.remove(i)
                    layer.insert(min(lead, len(layer)), i)
            todo = list(self.layers[0][:self.layers[0].index(zin)])
            while todo:  # the ports above and the lanes that carry their wires on
                i = todo.pop()
                if i in self.above:
                    continue
                self.above.add(i)
                todo += [e.v for e in self.succ_edges[i] if e.v.kind == 'dummy']
        for layer in self.layers:  # satellites (NF021) head or end their column
            sats = [i for i in layer if getattr(i, 'sat', False)]
            if sats:
                n = len(layer)
                top = [i for i in sats if layer.index(i) < n / 2]
                bottom = [i for i in sats if i not in top]
                rest = [i for i in layer if i not in sats]
                k = 1 if rest and rest[0].pin and rest[0].kind == 'node' else 0
                layer[:] = rest[:k] + top + rest[k:] + bottom
        self._set_comm_state(self.comm_items, comm_state)
        for k, layer in enumerate(self.layers):
            for n, i in enumerate(layer):
                i.order = n
        # lanes beyond the first or last node of a column in a zone (graph._gap)
        self.outer = set()
        if zin is not None and P.ZONE_LANE_GAP != P.LANE_GAP:
            for layer in self.layers:
                reals = [n for n, i in enumerate(layer) if not i.is_point]
                if not reals:
                    continue
                f, l = reals[0], reals[-1]
                if f > 0:
                    self.outer.add((id(layer[f - 1]), id(layer[f])))
                if l + 1 < len(layer):
                    self.outer.add((id(layer[l]), id(layer[l + 1])))
        # provisional y that matches the chosen order (used to rank alignments): one pass of
        # barycenters, rounded so that tiny float differences cannot change any decision
        for k, layer in enumerate(self.layers):
            prev = None
            for i in layer:
                ts = [self._sock_y(e.u, e.uk, True) - i.ins.get(e.vk, (0, 0))[1] for e in self.pred_edges[i]]
                y = sum(ts) / len(ts) if ts else (prev.y + prev.h if prev else 0.0)
                if prev is not None:
                    y = max(y, prev.y + prev.h + self._gap(prev, i))
                i.y = round(y, 1)
                prev = i

    def _desired(self, layer, down):
        """Barycenters: for each item, the mean height its links want (main inputs weigh 4), from
        the column before (down) or after (up)."""
        desired = {}
        for i in layer:
            es = self.pred_edges[i] if down else self.succ_edges[i]
            tot = wsum = 0.0
            for e in es:
                w = 4.0 if e.main else 1.0
                if down:
                    t = self._sock_y(e.u, e.uk, True) - i.ins.get(e.vk, (0, 0))[1]
                else:
                    t = self._sock_y(e.v, e.vk, False) - i.outs.get(e.uk, (0, 0))[1]
                tot += w * t
                wsum += w
            desired[i] = tot / wsum if wsum else i.y
        return desired

    def _gap_crossings(self, k):
        """Crossings between columns k and k+1 (links compared by socket heights)."""
        if k < 0 or k >= self.R:
            return 0
        pts = [(self._sock_y(e.u, e.uk, True), self._sock_y(e.v, e.vk, False))
               for i in self.layers[k] for e in self.succ_edges[i]]
        total = 0
        for a in range(len(pts)):
            p1, q1 = pts[a]
            for b in range(a + 1, len(pts)):
                p2, q2 = pts[b]
                if (p1 - p2) * (q1 - q2) < -1e-6:
                    total += 1
        return total

    def _restack(self, layer):
        """Positions of a layer after its order changed: same top, items stacked with gaps."""
        if not layer:
            return
        y = min(i.y for i in layer)
        for i in layer:
            i.y = y
            y += i.h + self._gap(i, i)

    def _transpose(self, layers, fixed_real, down):
        """Swap neighbours in a column while that removes crossings (pins stay first/last)."""
        rng = range(self.R + 1) if down else range(self.R, -1, -1)
        for k in rng:
            layer = layers[k]
            improved = True
            rounds = 0
            while improved and rounds < 4:
                improved = False
                rounds += 1
                for n in range(len(layer) - 1):
                    a, b = layer[n], layer[n + 1]
                    if fixed_real and not a.is_point and not b.is_point:
                        continue
                    ys = [i.y for i in layer]
                    before = self._gap_crossings(k - 1) + self._gap_crossings(k)
                    layer[n], layer[n + 1] = b, a
                    self._restack(layer)
                    after = self._gap_crossings(k - 1) + self._gap_crossings(k)
                    if after < before:
                        improved = True
                    else:
                        layer[n], layer[n + 1] = a, b
                        for i, y in zip(layer, ys):
                            i.y = y

    def _comm_units(self):
        """The commutative pairs of the items, as units (item, (a, b), links into the pair): a
        node has one pair (Add, Multiply, AND, Equal, ...); a frame or zone may have several,
        each a pair of its ports that a swap inside it exchanges (layout.py)."""
        units = []
        for i in self.items:
            c = getattr(i, 'comm', None)
            for pair in (c if isinstance(c, list) else [c] if c else []):
                es = [e for e in self.pred_edges[i] if e.vk0 in pair]
                if es:
                    units.append((i, tuple(pair), es))
        return units

    def _comm_state(self, comm):
        """Input keys of the links into each commutative pair (its swap state)."""
        return [tuple(e.vk for e in es) for _, _, es in comm]

    def _set_comm_state(self, comm, state):
        """Apply a swap state, and list the pairs whose links differ from the tree."""
        for (_, _, es), vks in zip(comm, state):
            for e, vk in zip(es, vks):
                e.vk = vk
        self.swapped = []
        for i, (a, b), es in comm:
            if any(e.vk != e.vk0 for e in es):
                self.swapped.append((i.id, a, b))

    def _swap_inputs(self, comm):
        """Exchange the links of a commutative pair (Add, Multiply, AND, Equal, ...) when that
        removes crossings in the gap before the node."""
        for i, (a, b), es in comm:
            k = i.rank - 1
            before = self._gap_crossings(k)
            for e in es:
                e.vk = b if e.vk == a else a
            if self._gap_crossings(k) >= before:
                for e in es:
                    e.vk = b if e.vk == a else a

    def _guess_oy(self, i):
        """Original height for a dummy or port (keep mode): that of the socket it carries."""
        if i.kind == 'pin_in':
            es = self.succ_edges[i]
            ys = [e.v.oy + e.v.ins.get(e.vk, (0, 0))[1] for e in es if e.v.oy is not None]
            return min(ys) if ys else 0.0
        es = self.pred_edges[i]
        for e in es:
            if e.u.oy is None:
                e.u.oy = self._guess_oy(e.u)
            return e.u.oy + e.u.outs.get(e.uk, (0, 0))[1]
        return 0.0
