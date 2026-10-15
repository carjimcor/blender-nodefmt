# SPDX-License-Identifier: GPL-3.0-or-later
"""Columns: x positions of the columns and of the vertical routing tracks between them.

Entry points: assign_x() (columns, track order, satellites) and shelf() (items with no link).
"""
from . import params as P
from .graph import _name, snap_down, snap_up


class ColumnsMixin:
    """Column x positions and track order."""

    def assign_x(self):
        """Columns and tracks. A node or block with no links out (the end of a side branch) may
        stick out of its column into the next ones, if nothing there is in its way."""
        sats = self._sat_groups()
        hang = {i for i in self.items if P.OVERHANG and not i.is_point and not self.succ_edges[i] and i.pin is None}
        hang -= set(sats)
        while True:
            self._assign_x(hang, sats)
            bad = self._in_the_way(hang)
            if not bad:
                break
            hang -= bad
        if sats:
            self._place_sats(sats)
            self._assign_x(hang, sats)  # tracks for the links of the satellites as placed

    def _label_room(self, k, tags, bends, slot):
        """NF041: room gap k needs for the labels of its labelled tracks (self.label_w), as (column
        edge to first track, first track to next column). Blender centres a wire's label above
        each of its bends; where that text would reach a node beside it, the gap widens so the
        text clears it by LABEL_CLEAR."""
        from . import labels as L
        lw = getattr(self, 'label_w', None)
        if not lw:
            return 0.0, 0.0
        near = [i for layer in getattr(self, 'layers', [])[k:k + 2] for i in layer if not i.is_point]
        left = right = 0.0
        for t in tags:
            n = slot[t]
            w = lw.get(t)
            if not w:
                continue
            ys = {y for y0, y1, _ in bends[t] for y in (y0, y1)}
            if not any(i.y < y - L.ABOVE and y - L.ABOVE - L.HEIGHT < i.y + i.h for y in ys for i in near):
                continue
            half = w / 2 + L.PAD + P.LABEL_CLEAR
            left = max(left, half - n * P.TRACK)
            right = max(right, half + n * P.TRACK)
        return left, right

    def _sat_groups(self):
        """Satellites (ranking.py, NF021) that head or end their column: {item: 'top' | 'bottom'}.
        One that ended up between other items is laid out as a plain item of its column."""
        out = {}
        for layer in getattr(self, 'layers', []):
            for n, i in enumerate(layer):
                if not getattr(i, 'sat', False):
                    continue
                if all(getattr(j, 'sat', False) for j in layer[:n]):
                    out[i] = 'top'
                elif all(getattr(j, 'sat', False) for j in layer[n + 1:]):
                    out[i] = 'bottom'
        return out

    def _place_sats(self, sats):
        """A satellite reaches left over the columns before its own; it goes above (top) or
        below (bottom) everything there, items and wires, with a node gap."""
        segs = self._route()
        for k, layer in enumerate(self.layers):
            top = [i for i in layer if sats.get(i) == 'top']
            bottom = [i for i in layer if sats.get(i) == 'bottom']
            for group, up in ((top[::-1], True), (bottom, False)):
                prev = None
                for s in group:
                    # the part that reaches over earlier columns (its own column is stacked)
                    x0, x1 = s.x - P.COL_GAP / 2, self.col_x[s.rank]
                    lo, hi = [], []
                    for j in (self.items if x0 < x1 else ()):
                        if j.rank >= s.rank:
                            continue
                        jx1 = j.x + (0 if j.is_point else j.w)
                        if j.x < x1 and jx1 > x0:
                            lo.append(j.y)
                            hi.append(j.y + (0 if j.is_point else j.h))
                    for tag, p, q in (segs if x0 < x1 else ()):
                        if min(p[0], q[0]) < x1 and max(p[0], q[0]) > x0:
                            lo.append(min(p[1], q[1]))
                            hi.append(max(p[1], q[1]))
                    if up:
                        if lo:
                            s.y = min(s.y, min(lo) - P.NODE_GAP - s.h)
                        if prev is not None:
                            s.y = min(s.y, prev.y - P.NODE_GAP - s.h)
                    else:
                        if hi:
                            s.y = max(s.y, max(hi) + P.NODE_GAP)
                        if prev is not None:
                            s.y = max(s.y, prev.y + prev.h + P.NODE_GAP)
                    prev = s

    def _in_the_way(self, hang):
        """Items of `hang` that may not overhang: a node or a wire of a later column is in the way."""
        bad = set()
        segs = None
        for i in hang:
            right = self.col_x[i.rank] + self.colw[i.rank]
            if i.x + i.w <= right + P.EPS:
                continue
            x0, y0, x1, y1 = i.x, i.y - P.NODE_GAP / 2, i.x + i.w + P.COL_GAP / 2, i.y + i.h + P.NODE_GAP / 2
            for j in self.items:
                if j is i or j.rank <= i.rank:
                    continue
                jx1 = j.x + (0 if j.is_point else j.w)
                jy1 = j.y + (0 if j.is_point else j.h)
                if j.x < x1 and jx1 > x0 and j.y < y1 and jy1 > y0:
                    bad.add(i)
                    break
            if i in bad:
                continue
            if segs is None:
                segs = self._route()
            for _, p, q in segs:
                sx0, sx1 = sorted((p[0], q[0]))
                sy0, sy1 = sorted((p[1], q[1]))
                if sx0 < x1 and sx1 > right + P.EPS and sy0 < y1 and sy1 > y0:
                    bad.add(i)
                    break
        return bad

    def _assign_x(self, hang, sats=()):
        """Column widths and x positions, and the x of every routing track. A gap is wide enough for
        its tracks (TRACK apart) and at least COL_GAP; tracks are centred in it."""
        colw = [0.0] * (self.R + 1)
        for i in self.items:
            if not i.is_point and i not in hang and i not in sats:
                colw[i.rank] = max(colw[i.rank], i.w)
        self.colw = colw
        bends = [{} for _ in range(self.R)]  # gap -> tag -> [(y_from, y_to, node entered)]
        for e in self.edges:
            k = e.u.rank
            t = self._turn_y(e)
            if t is not None:  # every link that is not straight turns on a track
                bends[k].setdefault(e.tag, []).append((self._sock_y(e.u, e.uk, True), t, _node_of(e.v)))
        self.bends = bends
        self.track_x = [{} for _ in range(self.R)]
        col_x = [0.0] * (self.R + 1)
        # wires drawn outside a box (NF023 a stack's side wires, NF035 fans) on the right of its
        # column or in the gap before it: the tracks of a gap keep clear of them
        reach_r, reach_l = [0.0] * (self.R + 1), [0.0] * (self.R + 1)
        for i in self.items:
            if not i.is_point and i not in hang and i not in sats:
                reach_r[i.rank] = max(reach_r[i.rank], i.w + getattr(i, 'reach_r', 0.0) - colw[i.rank])
                reach_l[i.rank] = max(reach_l[i.rank], getattr(i, 'reach_l', 0.0))
        for k in range(self.R + 1):
            if k == 0:
                col_x[0] = 0.0
            if k == self.R:
                break
            base = snap_up(col_x[k] + colw[k] + reach_r[k])
            tags = self._order_tracks(bends[k])
            slot = _slots(tags, bends[k])
            T = max(slot.values(), default=-1) + 1
            lr = reach_l[k + 1]
            nxt = max(base + P.TRACK * (T + 1) + lr, snap_up(col_x[k] + colw[k] + P.COL_GAP + reach_r[k] + lr))
            # centre the tracks in the gap (between the side wires of stacks)
            free = (nxt - lr - base) - P.TRACK * (T + 1)
            start = base + snap_down(free / 2) + P.TRACK
            left, right = self._label_room(k, tags, bends[k], slot)
            if left or right:  # NF041: a labelled track keeps its labels clear of the nodes beside it
                start = max(start, snap_up(col_x[k] + colw[k] + left))
                # the gap holds every track after the shift (the next column a track away from the last)
                nxt = max(nxt, snap_up(start + right), snap_up(start + P.TRACK * T + lr))
            for t in tags:
                self.track_x[k][t] = start + P.TRACK * slot[t]
            col_x[k + 1] = nxt
        self.col_x = col_x
        for i in self.items:
            if i.is_point:
                i.x = col_x[i.rank] + colw[i.rank]
            elif i in sats:  # a satellite ends at its column's right edge and reaches left
                i.x = col_x[i.rank] + colw[i.rank] - i.w
            else:
                i.x = col_x[i.rank]

    def _order_tracks(self, segs):
        """Memoised _order_tracks_ (the same gap is ordered many times during the search)."""
        key = tuple(sorted((t, tuple(v)) for t, v in segs.items()))
        memo = self.__dict__.setdefault('_track_memo', {})
        if key not in memo:
            memo[key] = self._order_tracks_(segs)
        return list(memo[key])

    def _order_tracks_(self, segs):
        """Left-to-right order of the tracks of one gap with the fewest crossings.

        A track (one source tag) is entered at the source height and left at its destination
        heights. With track a left of b, b's entry and a's exits cross the other's vertical where
        they fall inside its span. The cost is additive over pairs (a linear ordering problem):
        solved exactly for up to EXACT_TRACKS tracks, else heuristically. Crossings inside a
        bundle and a wire running into another's corner cost more, which nests a bundle's tracks
        like stairs."""
        tags = sorted(segs, key=repr)
        n = len(tags)
        if n <= 1:
            return tags
        info = {}
        for t in tags:
            ys = segs[t]
            src = ys[0][0]
            outs = [b for _, b, _ in ys]
            info[t] = (src, outs, min([src] + outs), max([src] + outs), {v for _, _, v in ys})

        def pair(a, b):
            """Crossings (weighted) when track a is left of track b."""
            _sa, oa, lo_a, hi_a, va = info[a]
            sb, _ob, lo_b, hi_b, vb = info[b]
            w = P.TRACK_BUNDLE if (a[0] == b[0] or va & vb) else 1.0
            c = 0.0
            if lo_a + P.EPS < sb < hi_a - P.EPS:      # b's entry passes a's vertical
                c += w
            elif lo_a - P.EPS <= sb <= hi_a + P.EPS and hi_a - lo_a > P.EPS:
                c += P.TRACK_TOUCH                   # b's entry runs into a's corner
            for y in oa:                             # a's exits pass b's vertical
                if lo_b + P.EPS < y < hi_b - P.EPS:
                    c += w
                elif lo_b - P.EPS <= y <= hi_b + P.EPS and hi_b - lo_b > P.EPS:
                    c += P.TRACK_TOUCH
            return c

        W = [[0.0 if i == j else pair(tags[i], tags[j]) for j in range(n)] for i in range(n)]
        if n <= P.EXACT_TRACKS:
            order = _exact_order(W)
        else:
            order = _heuristic_order(W, tags, info)
        return [tags[i] for i in order]

    def shelf(self, alone):
        """Put the items with no link at all (a frame of notes, a block nothing uses) under the
        layout (NF021), biggest first: each takes the spot right below what is there, at a column
        edge or after an item and within the layout's width if it fits, that adds the least area
        to the box (then the highest, then the leftmost). Without NF021: in a row underneath."""
        if not alone:
            return
        if not P.SATELLITES:  # NF021 off
            ys = [i.y + i.h for i in self.items]
            y = snap_up(max(ys, default=0.0) + P.COL_GAP)
            x = 0.0
            for i in sorted(alone, key=lambda i: _name(i)):
                i.x, i.y, i.rank = x, y, 0
                x = snap_up(x + i.w + P.COL_GAP)
                self.items.append(i)
            return
        occ = [(i.x, i.y, i.x + i.w, i.y + i.h) for i in self.items if not i.is_point]
        occ += [(min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])) for _, p, q in self._route()]
        if not occ:
            occ = [(0.0, 0.0, 0.0, 0.0)]
        for i in sorted(alone, key=lambda i: (-i.w * i.h, _name(i))):
            x0 = min(r[0] for r in occ)
            y0 = min(r[1] for r in occ)
            x1 = max(r[2] for r in occ)
            y1 = max(r[3] for r in occ)
            xs = ({snap_up(x0)} | {snap_up(r[2] + P.COL_GAP) for r in occ}
                  | {snap_up(c) for c in getattr(self, 'col_x', ())})
            inside = [x for x in xs if x0 <= x and x + i.w <= x1]
            xs = inside or [snap_up(x0)]
            best = None
            for x in sorted(xs):
                below = [r[3] for r in occ if r[0] < x + i.w + P.COL_GAP and r[2] > x - P.COL_GAP]
                y = snap_up((max(below) if below else y0) + P.COL_GAP)
                area = (max(x1, x + i.w) - min(x0, x)) * (max(y1, y + i.h) - min(y0, y))
                key = (round(area, 3), y, x)
                if best is None or key < best[0]:
                    best = (key, x, y)
            _, i.x, i.y = best
            i.rank = 0
            self.items.append(i)
            occ.append((i.x, i.y, i.x + i.w, i.y + i.h))


def _slots(tags, segs):
    """The x slot of each track of a gap, tags in their left-to-right order. With NF036
    (TRACK_SHARE), a track takes the leftmost slot right of every earlier track whose height
    range comes within TRACK_SHARE of its own: overlapping tracks keep their order (no crossing
    changes) and tracks one above the other share an x. Without it, each track has its own."""
    if not P.TRACK_SHARE:
        return {t: n for n, t in enumerate(tags)}
    span, slot = {}, {}
    for t in tags:
        ys = [segs[t][0][0]] + [b for _, b, _ in segs[t]]
        lo, hi = min(ys), max(ys)
        s = 0
        for u, (ulo, uhi) in span.items():
            if lo < uhi + P.TRACK_SHARE and ulo < hi + P.TRACK_SHARE:
                s = max(s, slot[u] + 1)
        span[t], slot[t] = (lo, hi), s
    return slot


def _node_of(item):
    """The node a routed link enters (dummies and ports stand for themselves)."""
    return item.id


def _exact_order(W):
    """Order of 0..n-1 minimising sum(W[a][b] for a placed left of b): dynamic programming over
    subsets (Held-Karp style), O(2^n n^2). Ties go to the lower index, so the result is stable."""
    n = len(W)
    full = (1 << n) - 1
    best = {0: (0.0, ())}
    for mask in range(full + 1):
        if mask not in best:
            continue
        c, seq = best[mask]
        for b in range(n):
            if mask & (1 << b):
                continue
            add = sum(W[a][b] for a in seq)
            m2 = mask | (1 << b)
            if m2 not in best or c + add < best[m2][0] - 1e-9:
                best[m2] = (c + add, seq + (b,))
    return list(best[full][1])


def _heuristic_order(W, tags, info):
    """Order for many tracks: sorted by how far they drop, then single tracks moved to the first
    position that lowers the cost, while one does."""
    n = len(W)
    order = sorted(range(n), key=lambda i: (info[tags[i]][0] - sum(info[tags[i]][1]) / len(info[tags[i]][1]),
                                            repr(tags[i])))

    def total(o):
        """Cost of a whole order."""
        return sum(W[o[x]][o[y]] for x in range(n) for y in range(x + 1, n))

    cur = total(order)
    # with whole-number weights (the defaults) partial sums are exact, so a move is costed
    # incrementally (what the track adds where it goes minus where it is); else total() in full
    exact = all(float(w).is_integer() and abs(w) < 2 ** 40 for row in W for w in row)
    for _ in range(4 * n):
        improved = False
        for x in range(n):
            t = order[x]
            rest = order[:x] + order[x + 1:]
            if exact:
                # what t adds when inserted at y in rest: tracks before it, and after it
                adds, before, after = [], 0.0, sum(W[t][b] for b in rest)
                for y in range(n):
                    adds.append(before + after)
                    if y < n - 1:
                        before += W[rest[y]][t]
                        after -= W[t][rest[y]]
            for y in range(n):
                if y == x:
                    continue
                if exact:
                    c = cur - adds[x] + adds[y]
                    if c < cur - 1e-9:
                        order, cur, improved = rest[:y] + [t] + rest[y:], c, True
                        break
                    continue
                cand = rest[:y] + [t] + rest[y:]
                c = total(cand)
                if c < cur - 1e-9:
                    order, cur, improved = cand, c, True
                    break
            if improved:
                break
        if not improved:
            break
    return order
