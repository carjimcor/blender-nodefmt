# SPDX-License-Identifier: GPL-3.0-or-later
"""Search: local search on the choices of a layout, and the final vertical slide.

A layout is fully determined by a Cand (graph.Cand). The local search (improve) tries moves on
it and keeps one when the whole layout costs less (cost.py). Seeds other than 0 (only when
P.SEEDS > 1) shuffle the moves, so different seeds explore different layouts.

The slide pass runs once, on the chosen layout: it moves a group of nodes held together by
straight links up or down so that one more link becomes straight, if nothing overlaps and the
cost drops.
"""
from itertools import pairwise

from . import params as P
from .graph import _name as _key

# the order in which _moves lists the kinds of move
_ORDER = {'port': 0, 'sat': 1, 'lane': 2, 'bundle': 3, 'fan': 4, 'comm': 5, 'placer': 6, 'bend': 7, 'node': 8,
          'swap': 9}


class SearchMixin:
    """Local search over candidates, and the slide pass."""

    def _evaluate(self, cand):
        """Lay out a candidate in full and return its cost."""
        self.use(cand)
        self.assign_y()
        self.assign_x()
        return self.cost()

    def _trial(self, cand):
        """The cost of a candidate tried by the local search, laid out only the first time.

        A layout depends only on its candidate (not on its origin), so a candidate seen before
        is taken from a memo, with the links it aligned (the 'bend' moves need them). A memo hit
        still counts against the budget, so the search takes the same steps either way."""
        key = (tuple(map(tuple, cand.layers)), tuple(cand.comm), cand.banned, cand.placer, cand.zone)
        memo = self.__dict__.setdefault('_eval_memo', {})
        hit = memo.get(key)
        if hit is not None:
            self.aligned = list(hit[1])
            return hit[0]
        c = self._evaluate(cand)
        memo[key] = (c, tuple(getattr(self, 'aligned', ())))
        return c

    def _moves(self, cur):
        """Candidate moves from the current state, as functions returning a new Cand or None."""
        keep = self.mode == 'keep'
        moves = []
        # swap two neighbours in a column
        for k in range(self.R + 1):
            for n in range(len(cur.layers[k]) - 1):
                a, b = cur.layers[k][n], cur.layers[k][n + 1]
                if keep and not a.is_point and not b.is_point:
                    continue

                def swap(cur, k=k, a=a, b=b):
                    """Exchange two neighbours of a column."""
                    layers = [list(l) for l in cur.layers]
                    if a not in layers[k] or b not in layers[k]:
                        return None
                    i, j = layers[k].index(a), layers[k].index(b)
                    layers[k][i], layers[k][j] = b, a
                    return cur._replace(layers=layers)
                moves.append(('swap', swap))
        # a whole lane (the dummies of one long link) to the top or bottom of its columns
        sides = ('top', 'bottom') + (('top_in', 'bottom_in') if P.LANE_SIDES else ())
        for tag in sorted({i.tag for i in self.items if i.kind == 'dummy'}, key=repr):
            for where in sides:
                moves.append(('lane', lambda cur, tag=tag, where=where: self._move_lane(cur, tag, where)))
        # all lanes leaving one node, in socket order, to the top or bottom of their columns:
        # parallel buses that stay nested (the staircase of a hand-made layout)
        by_node = {}
        for i in self.items:
            if i.kind == 'dummy':
                by_node.setdefault(i.tag[0], set()).add(i.tag)
        for node, tags in sorted(by_node.items(), key=repr):
            if len(tags) < 2:
                continue
            for where in sides:
                moves.append(('bundle', lambda cur, tags=tags, where=where: self._move_lanes(cur, tags, where)))
        # everything one node feeds (_fan) to the top or bottom of their columns: a fan of wires
        # that leaves to one side and crosses nothing
        if not keep and P.LANE_SIDES:
            for i in sorted((i for i in self.items if not i.is_point and len(self.succ_edges[i]) >= 2), key=_key):
                fan = self._fan(i)
                if len(fan) >= 2:
                    for where in ('top', 'bottom'):
                        moves.append(('fan', lambda cur, fan=fan, where=where: self._move_set(cur, fan, where)))
        if not keep:  # a node to the top or bottom of its column
            for k in range(self.R + 1):
                for i in cur.layers[k]:
                    if i.is_point or i.pin:
                        continue
                    for where in ('top', 'bottom'):
                        moves.append(('node', lambda cur, i=i, k=k, where=where: self._move_item(cur, i, k, where)))
        # let the end of a lane bend, so the links next to it can be straight
        for e in [e for e in getattr(self, 'aligned', []) if e.u.is_point and e.v.kind in ('node', 'compound')]:
            moves.append(('bend', lambda cur, e=e: cur._replace(banned=cur.banned | {e})
                          if e not in cur.banned else None))
        # a satellite (NF021) to either end of the top or bottom group of its column
        for k in range(self.R + 1):
            for i in [i for i in cur.layers[k] if getattr(i, 'sat', False)]:
                for where in ('top', 'top_in', 'bottom_in', 'bottom'):
                    moves.append(('sat', lambda cur, i=i, k=k, where=where: self._move_sat(cur, i, k, where)))
        # a port of a zone above the zone input (and back): its wire enters over the zone input
        zin = self._zone_input()
        if zin is not None and P.PORTS_ABOVE and not keep:
            for p in sorted((i for i in self.items if i.kind == 'pin_in'), key=_key):
                moves.append(('port', lambda cur, p=p, zin=zin: self._port_above(cur, p, zin)))
        # swap the links of a commutative pair
        for j in range(len(self.comm_items)):
            def flip(cur, j=j):
                """Exchange the links of commutative pair j."""
                state = list(cur.comm)
                state[j] = self._flip(self.comm_items[j], state[j])
                return None if state[j] == cur.comm[j] else cur._replace(comm=state)
            moves.append(('comm', flip))
        # the other placement method
        for placer in P.PLACERS:
            moves.append(('placer', lambda cur, placer=placer: cur._replace(placer=placer)
                          if cur.placer != placer else None))
        # moves that change a whole side first: a small budget tries them before the many swaps
        moves.sort(key=lambda m: _ORDER.get(m[0], 9))
        return moves

    def _move_lane(self, cur, tag, where):
        """A lane (the dummies of one tag) to the top or bottom of its columns."""
        layers = [list(l) for l in cur.layers]
        moved = False
        for layer in layers:
            ds = [i for i in layer if i.kind == 'dummy' and i.tag == tag]
            if not ds:
                continue
            rest = [i for i in layer if i not in ds]
            new = _insert_at(rest, ds, where)
            if new is not None and new != layer:
                layer[:] = new
                moved = True
        return cur._replace(layers=layers) if moved else None

    def _move_lanes(self, cur, tags, where):
        """Several lanes to the top or bottom of their columns, ordered by their source sockets."""
        layers = [list(l) for l in cur.layers]
        moved = False
        for layer in layers:
            ds = [i for i in layer if i.kind == 'dummy' and i.tag in tags]
            if not ds:
                continue
            ds.sort(key=lambda d: (self._src_y(d.tag), repr(d.tag)))
            rest = [i for i in layer if i not in ds]
            new = _insert_at(rest, ds, where)
            if new is not None and new != layer:
                layer[:] = new
                moved = True
        return cur._replace(layers=layers) if moved else None

    def _fan(self, i):
        """Items fed by item i: the lanes of its links and the nodes they reach in the column
        after i (pins excluded)."""
        out, todo = set(), [e.v for e in self.succ_edges[i]]
        while todo:
            v = todo.pop()
            if v in out or v.pin or v.kind in ('pin_in', 'pin_out'):
                continue
            if v.kind == 'dummy':
                out.add(v)
                todo += [e.v for e in self.succ_edges[v] if e.v.kind == 'dummy']
            elif v.rank == i.rank + 1:
                out.add(v)
        return frozenset(out)

    def _move_set(self, cur, items, where):
        """The items of a set to the top or bottom of their columns, keeping their order."""
        layers = [list(l) for l in cur.layers]
        moved = False
        for layer in layers:
            ds = [i for i in layer if i in items]
            if not ds:
                continue
            rest = [i for i in layer if i not in items]
            new = _insert_at(rest, ds, where)
            if new is not None and new != layer:
                layer[:] = new
                moved = True
        return cur._replace(layers=layers) if moved else None

    def _move_sat(self, cur, i, k, where):
        """Satellite i to the very top, the inner end of the top group, the inner end of the
        bottom group or the very bottom of column k."""
        layers = [list(l) for l in cur.layers]
        layer = layers[k]
        if i not in layer:
            return None
        rest = [j for j in layer if j is not i]
        sat = [n for n, j in enumerate(rest) if not getattr(j, 'sat', False)]
        if where == 'top':
            n = 1 if rest and rest[0].pin and rest[0].kind == 'node' else 0
        elif where == 'bottom':
            n = len(rest)
        elif where == 'top_in':
            n = sat[0] if sat else 0
        else:
            n = sat[-1] + 1 if sat else len(rest)
        new = rest[:n] + [i] + rest[n:]
        if new == layer:
            return None
        layers[k] = new
        return cur._replace(layers=layers)

    def _port_above(self, cur, p, zin):
        """Port p above the zone input if it is below, else right below it; the lanes of its
        wire go along to the top of their columns (or back right above the zone's nodes)."""
        layers = [list(l) for l in cur.layers]
        lay = layers[0]
        if p not in lay or zin not in lay:
            return None
        up = lay.index(p) > lay.index(zin)
        lay.remove(p)
        lay.insert(0 if up else lay.index(zin) + 1, p)
        lanes, todo = set(), [e.v for e in self.succ_edges[p] if e.v.kind == 'dummy']
        while todo:
            d = todo.pop()
            if d not in lanes:
                lanes.add(d)
                todo += [e.v for e in self.succ_edges[d] if e.v.kind == 'dummy']
        for layer in layers[1:]:
            ds = [i for i in layer if i in lanes]
            if ds:
                rest = [i for i in layer if i not in lanes]
                layer[:] = _insert_at(rest, ds, 'top' if up else 'top_in') or layer
        return cur._replace(layers=layers)

    def _src_y(self, tag):
        """Offset of a source socket in its node (orders the lanes of one node)."""
        for e in self.edges:
            if e.tag == tag and not e.u.is_point:
                return e.u.outs.get(e.uk, (0, 0))[1]
        return 0.0

    def _move_item(self, cur, item, k, where):
        """A node to the top or bottom of its column."""
        layers = [list(l) for l in cur.layers]
        layer = layers[k]
        if item not in layer:
            return None
        rest = [i for i in layer if i is not item]
        if where == 'top':
            n = 1 if rest and rest[0].pin and rest[0].kind == 'node' else 0
            new = rest[:n] + [item] + rest[n:]
        else:
            new = rest + [item]
        if new == layer:
            return None
        layers[k] = new
        return cur._replace(layers=layers)

    def improve(self, cand, cost, budget, rng=None):
        """Local search from `cand` (of cost `cost`) with at most `budget` layouts. Returns the
        best (cost, Cand) found; the layout is left in that state."""
        cur, best = cand, cost
        self._evaluate(cur)
        changed = True
        while changed and budget > 0:
            changed = False
            moves = self._moves(cur)
            if rng is not None:
                rng.shuffle(moves)
            for _, move in moves:
                if budget <= 0:
                    break
                trial = move(cur)
                if trial is None:
                    continue
                c = self._trial(trial)
                budget -= 1
                if c < best - 1e-6:
                    best, cur, changed = c, trial, True
        self._evaluate(cur)
        return best, cur

    def _flip(self, unit, vks):
        """The input keys of a commutative pair (ordering._comm_units) exchanged."""
        a, b = unit[1]
        return tuple(b if k == a else a if k == b else k for k in vks)

    # ------------------------------------------------------------------ slide
    def slide(self, budget=None):
        """Move groups of nodes up or down to make more links straight, at most `budget` layouts
        (P.SLIDE). Groups are joined by the links straight now, so a move never bends one, and
        must keep every column's order and gaps. Returns the cost."""
        budget = P.SLIDE if budget is None else budget
        cur = self.cost()
        while budget > 0:
            group = self._straight_groups()
            bent = [e for e in self.edges if abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)) > P.EPS
                    and not (e.u.is_point and e.v.is_point)]
            prio = self._priorities()
            bent.sort(key=lambda e: (prio.get(e, 3),
                                     abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)), repr(e)))
            done = False
            for e in bent:
                d = self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)
                for g, delta in ((group[e.v], d), (group[e.u], -d)):
                    if budget <= 0 or not self._shift_ok(g, delta):
                        continue
                    for i in g:
                        i.y += delta
                    self.assign_x()
                    c = self.cost()
                    budget -= 1
                    if c < cur - 1e-6:
                        cur, done = c, True
                        break
                    for i in g:
                        i.y -= delta
                if done:
                    break
            if not done:
                break
        self.assign_x()
        return self.cost()

    def _straight_groups(self):
        """item -> frozenset of the items joined to it by straight links."""
        parent = {i: i for i in self.items}

        def find(i):
            """Root of the group of item i (union-find with path halving)."""
            while parent[i] is not i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        for e in self.edges:
            if abs(self._sock_y(e.u, e.uk, True) - self._sock_y(e.v, e.vk, False)) <= P.EPS:
                parent[find(e.u)] = find(e.v)
        zin = self._zone_input()
        if zin is not None:  # the zone input stays put, and so does a level zone output
            for i in self.items:
                if i.pin and i.kind == 'node' and (i.pin == 'first' or not self._zone_free()):
                    parent[find(i)] = find(zin)
        groups = {}
        for i in self.items:
            groups.setdefault(find(i), set()).add(i)
        return {i: frozenset(groups[find(i)]) for i in self.items}

    def _shift_ok(self, g, delta):
        """True if moving the items of g by delta keeps every column in order with its gaps,
        and a zone's content below the zone input's top."""
        zin = self._zone_input()
        if abs(delta) <= P.EPS or (zin is not None and zin in g):
            return False
        for layer in self.layers:
            ys = [(i.y + (delta if i in g else 0.0), i) for i in layer]
            for (ya, a), (yb, b) in pairwise(ys):
                if yb < ya + a.h + self._gap(a, b) - 1e-6:
                    return False
            above = getattr(self, 'above', ())
            if zin is not None and any(i in g and i is not zin and i not in above and y < zin.y - 1e-6
                                       for y, i in ys):
                return False
        return True


def _insert_at(rest, ds, where):
    """Column `rest` with the lane items `ds` put at `where`: 'top' (after a zone input heading
    the column), 'bottom', 'top_in' (right above the first node) or 'bottom_in' (right below
    the last node); the inner places let a lane change sides without crossing other lanes (NF033).
    None if an inner place is asked for in a column without nodes."""
    if where == 'top':
        k = 1 if rest and rest[0].pin and rest[0].kind == 'node' else 0
    elif where == 'bottom':
        k = len(rest)
    else:
        real = [n for n, i in enumerate(rest) if not i.is_point]
        if not real:
            return None
        k = real[0] if where == 'top_in' else real[-1] + 1
        if where == 'top_in' and rest[k].pin and rest[k].kind == 'node':
            k += 1
    return rest[:k] + ds + rest[k:]
