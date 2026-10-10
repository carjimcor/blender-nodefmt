# SPDX-License-Identifier: GPL-3.0-or-later
"""Force-directed ordering: a second way to find the order of each column.

Like a graph view (Obsidian, d3-force): every link is a spring that pulls the two sockets it
joins to one height, every pair of items in a column (and, more weakly, in neighbouring columns)
repel each other, and items closer than their gap are pushed apart. The columns stay where the
ranking put them (left-to-right order comes from the topology); only heights move. After
P.FORCE_STEPS steps with a cooling step size, each column is ordered by the relaxed heights,
cleaned up by one round of neighbour transposition, and handed to the placement methods like any
order from the crossing reduction.
"""
from . import params as P
from .graph import Cand


class ForceMixin:
    """Order candidates from a force-directed relaxation of heights."""

    def force_cands(self, start, rng=None):
        """Candidates (one per placement method) from a force simulation that starts from the
        order `start` (a Cand); with a random generator the start heights are jittered."""
        self.use(start)
        ys = {i: i.y + i.h / 2 for i in self.items}  # centres
        if rng is not None:
            for i in ys:
                ys[i] += rng.uniform(-P.FORCE_JITTER, P.FORCE_JITTER)
        cols = [list(l) for l in self.layers]
        step = 0.5
        for it in range(P.FORCE_STEPS):
            f = {i: 0.0 for i in self.items}
            for e in self.edges:  # springs: socket heights level
                a = ys[e.u] - e.u.h / 2 + e.u.outs.get(e.uk, (0, 0))[1]
                b = ys[e.v] - e.v.h / 2 + e.v.ins.get(e.vk, (0, 0))[1]
                w = 2.0 if e.main else 1.0
                f[e.u] += w * (b - a)
                f[e.v] -= w * (b - a)
            for k, col in enumerate(cols):  # repulsion in a column, and from the next column
                others = cols[k + 1] if k + 1 < len(cols) else []
                for n, a in enumerate(col):
                    for b in col[n + 1:] + others:
                        d = ys[b] - ys[a]
                        need = (a.h + b.h) / 2 + self._gap(a, b)
                        same = b in col
                        dist = abs(d) or 1e-3
                        push = (P.FORCE_REPEL * need * need / (dist * dist)) * (1.0 if same else 0.2)
                        if same and dist < need:
                            push += 4.0 * (need - dist)
                        push = min(push, 200.0)
                        sgn = 1.0 if d >= 0 else -1.0
                        f[a] -= sgn * push
                        f[b] += sgn * push
            for i in self.items:
                if i.pin == 'first' and i.kind == 'node' and getattr(i, 'zmatch', None) is not None:
                    continue  # a zone input heads its column anyway
                ys[i] += step * max(-60.0, min(60.0, f[i]))
            step *= P.FORCE_COOL
        layers = [sorted(col, key=lambda i: (ys[i], repr(i.id))) for col in cols]
        self.layers = layers
        for k, layer in enumerate(layers):  # stack them in the new order for the clean-up
            y = 0.0
            for i in layer:
                i.y = y
                y += i.h + self._gap(i, i)
        self._transpose(layers, self.mode == 'keep', True)
        return [Cand([list(l) for l in layers], start.comm, frozenset(), placer, 'force') for placer in P.PLACERS]
