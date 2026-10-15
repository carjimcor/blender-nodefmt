# SPDX-License-Identifier: GPL-3.0-or-later
"""Relaxation: a second placement method, by springs instead of blocks.

Every link is a spring that pulls the sockets it joins to one height. Sweeping the columns down
and up, each item moves to the weighted mean of what its links want, and the column is restacked
in its order with the least weighted displacement (isotonic regression with gaps, by pool
adjacent violators). After P.RELAX_ITERS sweeps, nearly straight links are made straight by
moving whole groups of items, in order of link priority, as long as no column overlaps.

The search keeps whichever placement method gives the cheaper layout for each order.
"""

import math

from . import params as P


def _median(vals):
    """Weighted median of [(value, weight)]."""
    vals = sorted(vals)
    half = sum(w for _, w in vals) / 2
    acc = 0.0
    for v, w in vals:
        acc += w
        if acc >= half - 1e-9:
            return v
    return vals[-1][0]


class RelaxMixin:
    """Spring relaxation, then straightening."""

    def _link_weight(self, e):
        """Spring stiffness of a link: main inputs and geometry pull harder, lanes stay level."""
        w = 4.0 if e.main else (2.0 if e.geo else 1.0)
        if e.u.is_point and e.v.is_point:
            w = 2.0
        return w

    def relax_y(self):
        """Place items by relaxation, then straightening (see the module docstring)."""
        self.aligned = []
        zin = self._zone_input()
        zp = self._zone_pair()
        zout, zoff = (zp[1], zp[2]) if zp else (None, 0.0)
        mode = getattr(self, "zone", "level")
        iters = P.RELAX_ITERS
        if zin is not None and iters % 2 == 0:
            iters += 1  # a zone ends on a forward sweep: the zone input first, its content below it
        for it in range(iters):
            ks = range(self.R + 1) if it % 2 == 0 else range(self.R, -1, -1)
            for k in ks:
                layer = self.layers[k]
                want, weight = {}, {}
                for i in layer:
                    pulls = []  # (height of i that makes the link straight, weight)
                    for e in self.pred_edges[i]:
                        pulls.append((self._sock_y(e.u, e.uk, True) - i.ins.get(e.vk, (0, 0))[1], self._link_weight(e)))
                    for e in self.succ_edges[i]:
                        pulls.append(
                            (self._sock_y(e.v, e.vk, False) - i.outs.get(e.uk, (0, 0))[1], self._link_weight(e))
                        )
                    if zout is not None and i is zout:  # a zone's output and the zone input's line
                        if mode == "level":
                            pulls = [(zin.y + zoff, 1000.0)]
                        else:
                            pulls.append((zin.y + zoff, P.ZONE_LEVEL))
                    ws = sum(w for _, w in pulls)
                    if not ws:
                        want[i] = i.y
                    elif mode == "median" and i is zout:
                        want[i] = _median(pulls)
                    else:
                        want[i] = sum(v * w for v, w in pulls) / ws
                    weight[i] = ws or 0.1
                self._stack(layer, want, weight, zin)
        self._straighten()
        top = min((i.y for i in self.items), default=0.0)
        for i in self.items:  # whole units (Blender rounds node locations), top at 0
            i.y = math.floor(i.y - top + 0.5)

    def _stack(self, layer, want, weight, zin=None):
        """Positions for one column in its order: as close as possible (weighted least squares)
        to `want`, with each item at least its gap below the one above."""
        offs, o = [], 0.0
        for n, i in enumerate(layer):
            offs.append(o)
            if n + 1 < len(layer):
                o += i.h + self._gap(i, layer[n + 1])
        # pool adjacent violators on z = y - offset, which must be non-decreasing
        pools = []  # [sum w*z, sum w, count]
        for n, i in enumerate(layer):
            z = want[i] - offs[n]
            w = weight[i]
            pools.append([w * z, w, 1])
            while len(pools) > 1 and pools[-2][0] / pools[-2][1] > pools[-1][0] / pools[-1][1]:
                a = pools.pop()
                pools[-1][0] += a[0]
                pools[-1][1] += a[1]
                pools[-1][2] += a[2]
        n = 0
        for s, w, c in pools:
            for _ in range(c):
                layer[n].y = s / w + offs[n]
                n += 1
        if zin is not None:  # a zone's content hangs below the zone input's top line
            prev = None
            for i in layer:
                lo = zin.y if i is not zin and i not in getattr(self, "above", ()) else -1e18
                if prev is not None:
                    lo = max(lo, prev.y + prev.h + self._gap(prev, i))
                i.y = max(i.y, lo)
                prev = i

    def _straighten(self):
        """Straighten the links bent by at most P.STRAIGHTEN by moving groups of items (the smaller
        group first; banned links stay bent). Sets self.aligned."""
        prio = self._priorities()
        for _ in range(2):
            group = self._straight_groups()
            cands = []
            for e in self.edges:
                if e in self.banned:
                    continue
                d = self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)
                if P.EPS < abs(d) <= P.STRAIGHTEN:
                    cands.append((prio.get(e, 3), abs(d), repr(e), e))
            cands.sort(key=lambda c: c[:3])
            moved = False
            for _, _, _, e in cands:
                d = self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)
                if abs(d) <= P.EPS:
                    continue
                gv, gu = group[e.v], group[e.u]
                if gv is gu:
                    continue
                for g, delta in sorted(((gv, d), (gu, -d)), key=lambda c: len(c[0])):
                    if self._shift_ok(g, delta):
                        for i in g:
                            i.y += delta
                        merged = g | (gu if g is gv else gv)
                        for i in merged:
                            group[i] = merged
                        moved = True
                        break
            if not moved:
                break
        self.aligned = [
            e for e in self.edges if abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)) <= P.EPS
        ]
