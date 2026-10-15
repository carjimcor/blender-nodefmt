# SPDX-License-Identifier: GPL-3.0-or-later
"""Lay out a whole tree (pure Python): containers (zones, frames) inside out, then absolute
positions and reroute routes. Works on a model.Model; blend.py writes the result to Blender."""
import math

from . import engine, params as P, routes, rules as _rules, wires
from .graph import Result, snap_up
from .model import FLOW

PORT_D = engine.PORT_DIRECT  # border port at a socket of a first-column item
PORT_IN = '<port:in>'     # border port on the container's left edge
GROUP_OUTPUT = 'NodeGroupOutput'
# nodes that take the last column of the tree (the Group Output first: it anchors the layout)
OUTPUTS = (GROUP_OUTPUT, 'ShaderNodeOutputMaterial', 'ShaderNodeOutputWorld', 'ShaderNodeOutputLight',
           'ShaderNodeOutputAOV', 'ShaderNodeOutputLineStyle', 'CompositorNodeViewer', 'CompositorNodeOutputFile')


class Container:
    """A part of the tree laid out as one block: the root, a zone (input, output and everything
    between), a frame or a stack (rule NF023: a node and the chains of field nodes stacked above
    and below it). `all` holds its nodes, `direct` the ones not in a child container."""
    def __init__(self, kind, key, nodes):
        """A container of `kind` ('root', 'zone', 'frame', 'stack') named `key`."""
        self.kind, self.key, self.all = kind, key, set(nodes)
        self.children = []
        self.parent = None
        self.direct = set()


def containers(m, stacks=False):
    """Zones and frames that can be laid out as one block, nested as a tree; with stacks=True
    also the stacks of rule NF023 (see _stacks)."""
    succ = {}
    for s, d, _, _ in m.links:
        succ.setdefault(s[0], set()).add(d[0])
    real = set(m.real)
    zones = []
    for n in m.real:
        out = m.paired(n)
        if out is None or out not in real:
            continue
        seen, todo = {n, out}, [n]
        while todo:
            v = todo.pop()
            if v == out:
                continue
            for w in succ.get(v, ()):
                if w not in seen:
                    seen.add(w)
                    todo.append(w)
        z = Container('zone', n, seen)
        z.pair = (n, out)
        zones.append(z)
    zones.sort(key=lambda z: len(z.all))
    # sources used only inside one zone (and the nodes only they feed, Index -> Compare) join it
    # and every zone around it, so their wires stay short and nested zones stay nested
    pred = {}
    for s, d, _, _ in m.links:
        pred.setdefault(d[0], set()).add(s[0])
    for z in zones:
        inside = z.all - {z.pair[0]}  # a node feeding the zone input stays outside
        frame = m.parent(z.pair[0])
        cand = {n for n in m.real if succ.get(n) and not any(n in w.all for w in zones)
                and (n not in pred or m.parent(n) == frame)}
        while True:  # keep the nodes fed only by candidates and used only inside the zone
            drop = {n for n in cand if not pred.get(n, set()) <= cand or not succ[n] <= inside | cand}
            if not drop:
                break
            cand -= drop
        for w in [w for w in zones if z.all <= w.all]:
            w.all |= cand
    frames = []
    for f in m.frames:
        desc = set()
        for n in m.real:
            p = m.parent(n)
            while p is not None:
                if p == f:
                    desc.add(n)
                    break
                p = m.parent(p)
        if desc:
            frames.append(Container('frame', f, desc))
    kept = list(zones)
    for f in sorted(frames, key=lambda c: -len(c.all)):
        if all(not (f.all & c.all) or f.all <= c.all or c.all <= f.all for c in kept):
            kept.append(f)
    if stacks:
        for s in _stacks(m):
            if all(not (s.all & c.all) or s.all < c.all for c in kept):
                kept.append(s)
    return kept


def _stacks(m):
    """The stacks of rule NF023 stacked-fields: Containers keyed by the consumer node, with the
    chains `above` and `below` it (lists, first node first). A chain is up to STACK_MAX field
    nodes in a row, the first with nothing linked in, each with one link out, the last feeding
    one input of the consumer in the same frame (Index -> Compare -> Selection). A lone chain
    goes above if that crosses fewer of the consumer's other inputs (tie: input in the upper
    half); of several, the chain into the highest input goes above, the lowest below."""
    zone = set()
    for n in m.real:
        if m.paired(n):
            zone |= {n, m.paired(n)}
    outl, inl = {}, {}
    for s, d, _, sid in m.links:
        outl.setdefault(s[0], []).append((s, d, sid))
        inl.setdefault(d[0], []).append((s, d, sid))

    def plain(n):
        """True if node n can be a consumer: no zone node, output or reroute."""
        return n not in zone and m.type(n) not in OUTPUTS and m.type(n) != 'NodeReroute'

    def field(n):
        """True if node n can be part of a chain: plain, not a Group Input, no geometry socket."""
        return plain(n) and m.type(n) != 'NodeGroupInput' and \
            not any(s["type"] in FLOW for s in m.info[n]["socks"].values() if s["vis"])

    def chain(link, v):
        """The nodes of the chain that ends with `link` into v, first node first, or None."""
        nodes, s = [], link[0]
        while True:
            n = s[0]
            if not field(n) or m.parent(n) != m.parent(v) or len(outl.get(n, [])) != 1:
                return None
            nodes.insert(0, n)
            ins = inl.get(n, [])
            if not ins:
                return nodes
            if len(ins) != 1 or len(nodes) == P.STACK_MAX:
                return None
            s = ins[0][0]

    found = []
    for v in m.real:
        if not plain(v):
            continue
        h = m.box[v][3]
        chains, others = [], []
        for link in inl.get(v, []):
            s, d, sid = link
            key = m.slot_key(s, d, sid)
            c = None if key != d else chain(link, v)  # never into a multi-input slot
            (chains if c else others).append((m.ins[v][key][1], c))
        if not chains:
            continue
        chains.sort(key=lambda t: t[0])
        st = Container('stack', v, {v})
        st.above, st.below = [], []
        if len(chains) == 1:
            y, c = chains[0]
            up = sum(1 for o, _ in others if o < y)
            down = sum(1 for o, _ in others if o > y)
            if up < down or (up == down and y <= h / 2):
                st.above = c
            else:
                st.below = c
        else:
            st.above, st.below = chains[0][1], chains[-1][1]
        st.all |= set(st.above) | set(st.below)
        found.append(st)
    # a consumer can be a link of a longer chain: the biggest stack wins
    out, used = [], set()
    for st in sorted(found, key=lambda st: (-len(st.all), st.key)):
        if not st.all & used:
            used |= st.all
            out.append(st)
    return sorted(out, key=lambda st: st.key)


def nest(m, conts):
    """Nest the containers into a tree under a root; returns (root, {node: innermost container})."""
    root = Container('root', None, set(m.real))
    allc = [root] + conts

    def contains(a, b):
        """True if container a strictly contains container b."""
        if a is b:
            return False
        if a.kind == 'root':
            return True
        if b.all < a.all:
            return True
        return b.all == a.all and a.kind == 'frame' and b.kind == 'zone'

    conts.sort(key=lambda c: (c.kind, c.key))
    for c in conts:
        cands = [a for a in allc if contains(a, c)]
        c.parent = min(cands, key=lambda a: (len(a.all), a.kind == 'root', a.kind == 'zone'))
        c.parent.children.append(c)

    def depth(c):
        """Nesting depth of a container."""
        return 0 if c.parent is None else 1 + depth(c.parent)

    home = {}
    for n in m.real:
        cands = [c for c in allc if n in c.all]
        home[n] = max(cands, key=depth)  # the containers holding a node form a chain
        home[n].direct.add(n)
    return root, home


class Formatter:
    """Lays out a whole tree (model.Model): containers inside out, then absolute positions, reroute
    trees and labels. run() does it all; blend.apply writes the result.

    record=True fills self.snapshots (for tools/animate.py) with plain-data states: 'direct'
    (nodes where they were, links drawn straight, no reroutes), the engine phases of each
    container in its own coordinates (engine.snapshot_state), then 'final' (geometry()). The
    original reroutes are not in the model (see tools/dump_tree.py)."""

    def __init__(self, m, mode='relayout', swaps=True, record=False, rules=None):
        """Format model m in `mode` ('relayout' or 'keep'); swaps=False keeps commutative inputs as
        they are; record=True keeps snapshots of the phases; rules: the enabled rule codes
        (rules.py; default all)."""
        self.snapshots = [] if record else None
        self.m = m
        self.mode = mode
        self.rules = frozenset(rules if rules is not None else _rules.DEFAULT)
        self.swaps_on = swaps and 'NF011' in self.rules
        # NF041: the text width of the label of each labelled wire (by source socket)
        self.label_w = {}
        if 'NF041' in self.rules:
            from .labels import text_width
            for lab in m.data.get("labels", []):
                tag = tuple(lab["src"])
                w = lab.get("w") or text_width(lab["label"])
                self.label_w[tag] = max(w, self.label_w.get(tag, 0.0))
        self.loose_frames = set()
        self.swapped = []  # (node, gid a, gid b): links of a commutative pair exchanged

    def run(self, route=True):
        """Lay out the tree (run_steps() in one go). Returns self. route=False stops at the node
        positions (self.pos, self.home, self.node_items), all the copy plan of dup.py needs."""
        for _ in self.run_steps(route):
            pass
        return self

    def run_steps(self, route=True):
        """Lay out the tree as a generator of progress: ('layout', k, n) after each of the n
        containers (again with the same k when a zone output mode is tried), then ('routing',
        1, 1). A frame that would form a cycle as one block is laid out as loose nodes (the
        count starts again). route=False: see run()."""
        if self.snapshots is not None:
            self.snapshots.append({"phase": "direct", **self._direct()})
        while True:
            stacks = 'NF023' in self.rules and self.mode == 'relayout'
            conts = [c for c in containers(self.m, stacks)
                     if not (c.kind == 'frame' and c.key in self.loose_frames)]
            self.root, self.home = nest(self.m, conts)
            try:
                self.res, self.node_items, self.comp_items = {}, {}, {}
                self.ctx, self.applied = {}, {}
                # border swaps (_border_pairs): first-column ids, pairs the parent may exchange,
                # port pairs exchanged, and the container of each compound item
                self.rank0, self.exposed, self.flipped, self.cont_of = {}, {}, {}, {}
                self.swapped = []
                self.links = list(self.m.links)
                self._done, self._count = 0, len(conts) + 1
                yield from self.layout(self.root)
                break
            except engine.CycleError as e:
                # a frame whose block would form a cycle is laid out as loose nodes
                bad = [i.id for i in e.items if isinstance(i.id, tuple) and i.id[0] == 'frame']
                if not bad:
                    raise
                self.loose_frames.add(bad[0][1])
        self.place(self.root, route)
        yield ('routing', 1, 1)
        if self.snapshots is not None and route:
            self.snapshots.append({"phase": "final", **self.geometry()})

    def _recorder(self, c):
        """The snapshot callback for container c (None when not recording)."""
        if self.snapshots is None:
            return None

        def record(phase, state):
            """Keep one engine phase of container c."""
            self.snapshots.append({"phase": phase, "container": [c.kind, c.key], **state})
        return record

    def _direct(self):
        """The tree as it was, drawn with direct links (no reroutes): nodes at their old boxes."""
        m = self.m
        nodes = [{"name": n, "x": m.box[n][0], "y": m.box[n][1], "w": m.box[n][2], "h": m.box[n][3]}
                 for n in m.real]
        links = []
        for s, d, _, sid in m.links:
            a, b = m.box[s[0]], m.box[d[0]]
            ds, dd = m.outs[s[0]][s], m.slot_at(m.slot_key(s, d, sid))
            links.append({"a": [a[0] + ds[0], a[1] + ds[1]], "b": [b[0] + dd[0], b[1] + dd[1]], "src": list(s)})
        return {"nodes": nodes, "links": links}

    def item_of(self, c, name):
        """The item that stands for node `name` inside container c: the node itself, or the child
        container (compound) that holds it."""
        h = self.home[name]
        if h is c:
            return self.node_items[name]
        while h.parent is not c:
            h = h.parent
        return self.comp_items[id(h)]

    def layout(self, c):
        """Lay out container c, children first, and make it one compound item of its parent (a
        generator, see run_steps). A child zone may offer other heights for its output (engine
        zone output modes); c tries each and keeps the one cheapest for c and the child
        together, so a lowered zone output stays only if what follows the zone fits better."""
        for ch in c.children:
            yield from self.layout(ch)
        self._run(c)
        self._done += 1
        yield ('layout', self._done, self._count)
        for ch in sorted(c.children, key=lambda ch: (ch.kind, str(ch.key))):
            alts = getattr(self.res[id(ch)][1], 'alts', [])
            if len(alts) < 2:
                continue
            cur = self.res[id(ch)][1]
            best = (self.res[id(c)][1].cost + cur.cost, cur.zone_mode)
            for cost, mode in alts:
                if mode == cur.zone_mode:
                    continue
                self._use_alt(ch, mode)
                self._run(c)
                yield ('layout', self._done, self._count)
                total = self.res[id(c)][1].cost + cost
                if total < best[0] - 1e-9:
                    best = (total, mode)
            if self.res[id(ch)][1].zone_mode != best[1]:
                self._use_alt(ch, best[1])
                self._run(c)
        if c.kind != 'root':
            self._compound(c)

    def _run(self, c):
        """Build the items and edges of container c (its children as compound items), run the
        engine, apply the input swaps it chose (undoing those of an earlier run of c)."""
        if c.kind == 'stack':
            self._run_stack(c)
            return
        for v, a, b in self.applied.pop(id(c), []):
            self._exchange(v, a, b)  # undo: an exchange is its own inverse
        m = self.m
        items = []
        for name in sorted(c.direct):
            x, y, w, h = m.box[name]
            pin = None
            if c.kind == 'zone' and name == c.pair[0]:
                pin = 'first'
            elif c.kind == 'zone' and name == c.pair[1]:
                pin = 'last'
            elif m.type(name) in OUTPUTS and c.kind == 'root':
                pin = 'last'
            elif m.info[name].get("pin") and c.kind == 'root':
                pin = m.info[name]["pin"]  # a link to the rest of the tree (sort of a part)
            kind = 'label' if m.type(name) == 'NodeReroute' else 'node'  # a kept (labelled) reroute
            it = engine.Item(name, kind, w, h, dict(m.ins[name]), dict(m.outs[name]), x, y,
                             m.main.get(name), pin)
            it.own_column = bool(m.info[name].get("pin")) and c.kind == 'root'  # see ranking.rank
            it.geo_out = any(m.geo.get(g, False) for g in m.outs[name])
            it.src = not any(d[0] == name for _, d, _, _ in m.links)
            it.reach_l = m.fan_reach.get(name, 0.0)  # NF035: its fans, in the gap before its column
            if name in m.comm and self.swaps_on:
                it.comm = it.comm_pair = m.comm[name]
            if pin and c.kind == 'zone':  # zone input/output: sockets by identifier, to line them up
                side = m.outs if pin == 'first' else m.ins
                it.zmatch = {m.info[g[0]]["socks"][f"{g[1]}{g[2]}"]["id"]: g for g in side[name] if len(g) == 3}
                it.zgeo = {k: m.geo[g] for k, g in it.zmatch.items()}
            self.node_items[name] = it
            items.append(it)
        for ch in c.children:
            comp = self.comp_items[id(ch)]
            comp.comm = list(comp.comm_pairs) if comp.comm_pairs and self.swaps_on else None
            items.append(comp)
        inside = (lambda n: True) if c.kind == 'root' else (lambda n: n in c.all)
        # edges between children, and links crossing the container border
        edges, b_in, b_out = {}, [], []
        routes_of = {}
        for s, d0, _, sid in self.links:
            d = m.slot_key(s, d0, sid)
            routes_of[(s, d)] = m.old_route(s, d0, sid)
            si, di = inside(s[0]), inside(d[0])
            if si and di:
                a, b = self.item_of(c, s[0]), self.item_of(c, d[0])
                if a is b:
                    continue
                bk = d if b.kind in ('node', 'label') else self._port_key(self.cont_of[b.id], s, d)
                e = engine.Edge(a, s, b, bk, s, m.geo[s])
                e.route = m.old_route(s, d0, sid)
                edges[(a.id, s, b.id, bk)] = e
            elif di:
                b_in.append((s, d))
            elif si:
                b_out.append((s, d))
        # dry run of the ranking to know which border links reach a first/last column item
        probe = engine._Layout(items, list(edges.values()), self.mode)
        probe.rank()
        R = probe.R
        self.rank0[id(c)] = {i.id for i in items if i.rank == 0}
        ports_in, ports_out = {}, {}
        direct_in, direct_out = {}, {}
        all_edges = list(edges.values())
        for s, d in b_in:
            b = self.item_of(c, d[0])
            bk = d if b.kind in ('node', 'label') else self._port_key(self.cont_of[b.id], s, d)
            if b.rank == 0:
                key = (PORT_D, b.id, bk)
                direct_in[key] = (b, bk)
                b.comm = None  # fed from outside: the parent exchanges this pair (_border_pairs)
            else:
                key = (PORT_IN, s)
                if key not in ports_in:
                    p = engine.Item(('pin', s, c.kind, c.key), 'pin_in', pin='first')
                    p.tag = s
                    ports_in[key] = p
                    items.append(p)
                e = engine.Edge(ports_in[key], 'out', b, bk, s, m.geo[s])
                e.route = routes_of.get((s, d))
                if not any(x.u is e.u and x.v is b and x.vk == bk for x in all_edges):
                    all_edges.append(e)
        for s, d in b_out:
            a = self.item_of(c, s[0])
            if a.rank == R or a.pin == 'last':
                direct_out[s] = a
            elif s not in ports_out:
                p = engine.Item(('pout', s, c.kind, c.key), 'pin_out', pin='last')
                p.tag = s
                ports_out[s] = p
                items.append(p)
                e = engine.Edge(a, s, p, 'in', s, m.geo[s])
                e.route = routes_of.get((s, d))
                all_edges.append(e)
        for it in items:
            if it.kind == 'pin_in':
                it.ins = {}
                it.outs = {'out': (0, 0)}
            elif it.kind == 'pin_out':
                it.ins = {'in': (0, 0)}
                it.outs = {}
        pad = (0, 0, 0, 0)
        if c.kind == 'frame':
            pad = m.pads.get(c.key, (30, 40, 30, 30))
        elif c.kind == 'zone':
            pad = (0, 20, 0, 20)
        linked = set(direct_in)
        self.exposed[id(c)] = self._border_pairs(c, items, all_edges, direct_in)
        res = engine.layout(items, all_edges, self.mode, pad, self._recorder(c), self.label_w)
        # the last item: ports of unlinked inputs of a border pair (never the main input)
        self.ctx[id(c)] = (ports_in, direct_in, ports_out, direct_out, set(direct_in) - linked)
        self._apply(c, res)

    def _run_stack(self, c):
        """Lay out stack c (rule NF023) without the engine: one column, STACK_GAP apart, the
        chain above the consumer from its first node down, the chain below from its last node
        down. Each link leaves its node to the right, turns in the gap between the two nodes,
        runs back along the left of the column and enters its socket from the left. Links from
        outside reach the sockets directly; nothing is swapped. The block is as wide as its
        nodes; the side wires run in the gaps beside it (res.reach, see columns.py)."""
        m = self.m
        left = -P.STACK_TRACK  # the left track, in the gap before the column
        x = 0.0
        order = list(c.above) + [c.key] + list(reversed(c.below))
        items, y = [], 0.0
        for name in order:
            bx, by, w, h = m.box[name]
            it = engine.Item(name, 'node', w, h, dict(m.ins[name]), dict(m.outs[name]), bx, by)
            it.x, it.y = x, y
            self.node_items[name] = it
            items.append(it)
            y += h + P.STACK_GAP
        at = {it.id: it for it in items}
        segs = []
        width = right = max(it.x + it.w for it in items)
        for s, d0, _, sid in self.links:
            if s[0] not in c.all or d0[0] not in c.all:
                continue
            a, b = at[s[0]], at[d0[0]]
            key = m.slot_key(s, d0, sid)
            p = (a.x + a.outs[s][0], a.y + a.outs[s][1])
            q = (b.x + b.ins[key][0], b.y + b.ins[key][1])
            xr = a.x + a.w + P.STACK_TRACK
            right = max(right, xr)
            mid = a.y + a.h + P.STACK_GAP / 2 if a.y < b.y else a.y - P.STACK_GAP / 2
            pts = [p, (xr, p[1]), (xr, mid), (left, mid), (left, q[1]), q]
            for k in range(len(pts) - 1):
                segs.append((s, pts[k], pts[k + 1], (b.id, key) if k == len(pts) - 2 else None))
        direct_in, direct_out = {}, {}
        for s, d0, _, sid in self.links:
            if d0[0] in c.all and s[0] not in c.all:
                key = m.slot_key(s, d0, sid)
                direct_in[(PORT_D, d0[0], key)] = (at[d0[0]], key)
            elif s[0] in c.all and d0[0] not in c.all:
                direct_out[s] = at[s[0]]
        res = Result()
        res.items, res.segments, res.origin = items, segs, (0.0, 0.0)
        res.w, res.h = width, y - P.STACK_GAP
        res.reach = (P.STACK_TRACK, right - width)
        res.ranks, res.cost, res.alts, res.swapped, res.zone_mode = 1, 0.0, [], [], None
        res.placer, res.seconds, res.crossings, res.aligned = 'stack', 0.0, 0, 0
        self.rank0[id(c)] = set(c.all)
        self.exposed[id(c)] = {}
        self.ctx[id(c)] = ({}, direct_in, {}, direct_out, set())
        self._apply(c, res)

    def _border_pairs(self, c, items, edges, direct_in):
        """The commutative pairs of container c that its parent may exchange (rule NF011):
        {(port a, port b): (item, key a, key b, tags)}. c is laid out before its parent and
        cannot see where its incoming wires come from, so a swap that only exchanges two of its
        ports is left to the parent:

        - a first-column item whose pair is fed from outside c (PORT_DIRECT ports; tags None);
        - an item further right whose two links each come from a left-edge port feeding nothing
          else: exchanging the two ports' heights and wire tags swaps the pair (tags: sources).

        The item may be a child block with border pairs of its own, so a pair passes up through
        nested frames and zones."""
        out = {}
        if c.kind == 'root' or not self.swaps_on:
            return out
        for b in items:
            pairs = getattr(b, 'comm_pair', None) if b.kind == 'node' else getattr(b, 'comm_pairs', None)
            if not pairs:
                continue
            for ka, kb in ([pairs] if b.kind == 'node' else pairs):
                if b.rank == 0:
                    if ka not in b.ins or kb not in b.ins:
                        continue
                    pa, pb = (PORT_D, b.id, ka), (PORT_D, b.id, kb)
                    direct_in.setdefault(pa, (b, ka))  # an unlinked input (with the same value)
                    direct_in.setdefault(pb, (b, kb))
                    out[(pa, pb)] = (b.id, ka, kb, None)
                    continue
                into = {e.vk: e for e in edges if e.v is b and e.vk in (ka, kb)}
                if len(into) != 2 or into[ka].u is into[kb].u:
                    continue
                if not all(e.u.kind == 'pin_in' and sum(1 for f in edges if f.u is e.u) == 1
                           for e in into.values()):
                    continue
                ta, tb = into[ka].u.tag, into[kb].u.tag
                out[((PORT_IN, ta), (PORT_IN, tb))] = (b.id, ka, kb, (ta, tb))
        return out

    def _port_key(self, c, s, d):
        """The key of the port where the link from s to d enters container c (d inside c)."""
        b = self.item_of(c, d[0])
        if b.id not in self.rank0[id(c)]:
            return (PORT_IN, s)
        bk = d if b.kind in ('node', 'label') else self._port_key(self.cont_of[b.id], s, d)
        return (PORT_D, b.id, bk)

    def _apply(self, c, res):
        """Make res the layout of container c: its input swaps applied to the links."""
        for v, a, b in res.swapped:
            self._exchange(v, a, b)
        self.applied[id(c)] = list(res.swapped)
        self.res[id(c)] = (c, res)

    def _use_alt(self, c, mode):
        """Switch zone container c to its layout for zone output `mode` (see layout())."""
        for v, a, b in self.applied.pop(id(c), []):
            self._exchange(v, a, b)
        self._apply(c, self.res[id(c)][1].realize(mode))
        self._compound(c)

    def _exchange(self, v, a, b):
        """Exchange the commutative pair (a, b) of item v: the links of a node, or a border pair
        of a child block (_border_pairs): the pair inside it and, for two ports of its left edge,
        their heights and the tags of their wires. An exchange is its own inverse."""
        if not isinstance(v, tuple):
            self._swap(v, a, b)
            return
        ch = self.cont_of[v]
        item, ka, kb, tags = self.exposed[id(ch)][(a, b)]
        self._exchange(item, ka, kb)
        if tags is not None:
            self.flipped.setdefault(id(ch), set()).symmetric_difference_update({tags})
        comp = self.comp_items[id(ch)]  # its ports as they are now (the parent's result keeps it)
        comp.ins.clear()
        comp.ins.update(self._ports(ch)[0])

    def _compound(self, c):
        """Container c as one compound item of its parent: its box and the ports where links
        cross its border."""
        m = self.m
        res = self.res[id(c)][1]
        ins, outs = self._ports(c)
        nodes = [m.box[n] for n in c.all]
        comp = engine.Item((c.kind, c.key), 'compound', res.w, res.h, ins, outs,
                           min(b[0] for b in nodes), min(b[1] for b in nodes))
        comp.comm_pairs = sorted(self.exposed.get(id(c), {}), key=repr) or None
        self.cont_of[comp.id] = c
        comp.geo_out = any(m.geo.get(s, False) for s in outs)
        comp.res = res
        comp.big = res.ranks >= 3
        comp.reach_l, comp.reach_r = getattr(res, 'reach', (0.0, 0.0))  # a stack's side wires
        # NF035: the fans of the block's first column reach out on its left
        if m.fan:
            comp.reach_l = max([comp.reach_l] + [-dx for dx, _ in ins.values()])
        # main input: the zone input's main socket, else a geometry port, else the top port
        main = None
        if c.kind in ('zone', 'stack'):  # the main socket of the zone input or the consumer
            mk = m.main.get(c.pair[0] if c.kind == 'zone' else c.key)
            for key in ins:
                if key[0] == PORT_D and key[2] == mk:
                    main = key
        linked = [k for k in ins if k not in self.ctx[id(c)][4]]
        if main is None and linked:
            main = min(linked, key=lambda k: (not self._port_geo(k), ins[k][1]))
        comp.main_in = main
        self.comp_items[id(c)] = comp

    def _ports(self, c):
        """Offsets of the ports of container c in its box: inputs {key: (dx, dy)} and outputs
        {source: (dx, dy)}, with the port pairs its parent exchanged (_exchange)."""
        res = self.res[id(c)][1]
        ports_in, direct_in, ports_out, direct_out, _ = self.ctx[id(c)]
        ox, oy = res.origin
        ins, outs = {}, {}
        for key, p in ports_in.items():
            ins[key] = (0.0, p.y - oy)
        for key, (b, bk) in direct_in.items():
            dx, dy = b.ins[bk]
            ins[key] = (b.x + dx - ox, b.y + dy - oy)
        for s, p in ports_out.items():
            outs[s] = (res.w, p.y - oy)
        for s, a in direct_out.items():
            dx, dy = a.outs[s]
            outs[s] = (a.x + dx - ox, a.y + dy - oy)
        for ta, tb in self.flipped.get(id(c), ()):
            pa, pb = (PORT_IN, ta), (PORT_IN, tb)
            ins[pa], ins[pb] = ins[pb], ins[pa]
        return ins, outs

    def _swap(self, v, a, b):
        """Exchange the links of inputs a and b of node v. Its own inverse: self.swapped lists
        the pairs exchanged an odd number of times."""
        if (v, a, b) in self.swapped:
            self.swapped.remove((v, a, b))
        else:
            self.swapped.append((v, a, b))
        new = []
        for s, d, mu, sid in self.links:
            if d == a:
                d = b
            elif d == b:
                d = a
            new.append((s, d, mu, sid))
        self.links = sorted(new)

    def _port_geo(self, key):
        """True if a border port carries geometry."""
        if key[0] == PORT_IN:
            return self.m.geo.get(key[1], False)
        return False

    # ------------------------------------------------------------ placement
    def place(self, root, route=True):
        """Absolute positions: every container's local layout shifted to where its block sits;
        then (route=True) the reroute trees, the tidy pass and the labels."""
        m = self.m
        self.pos, self.segments = {}, []
        self._place(root, (0.0, 0.0))
        # the anchor (Group Output, else another output node, else the first node by name) stays
        # put, so formatting a formatted tree changes nothing
        outs = sorted((n for n in self.pos if m.type(n) in OUTPUTS), key=lambda n: (OUTPUTS.index(m.type(n)), n))
        outs = outs or sorted(self.pos)
        ref = outs[0]
        self.anchor = ref
        bx, by = m.box[ref][0], m.box[ref][1]
        px, py = self.pos[ref]
        off = (bx - px, by - py)  # exactly: two equal layouts land on the same spot
        if m.data.get("below"):
            # measured below y = 0 at a fractional UI scale (api.read_tree): the tree goes wholly
            # below 0, where Blender draws its rows as measured; once there it stays put
            top = min((y + off[1] for k, (_, y) in self.pos.items() if m.box[k][3] > 0), default=0.0)
            if top < 0:
                off = (off[0], off[1] + snap_up(-top))
        self.pos = {k: (x + off[0], y + off[1]) for k, (x, y) in self.pos.items()}
        self.segments = [(t, (p[0] + off[0], p[1] + off[1]), (q[0] + off[0], q[1] + off[1]), d)
                         for t, p, q, d in self.segments]
        if not route:
            return
        if m.fan:  # NF035: a link laid out to its fan point goes on from there to its slot
            segs = []
            for t, p, q, d in self.segments:
                if d is not None and d in m.fan:
                    x, y = self.pos[d[0]]
                    dx, dy = m.fan[d]
                    segs += [(t, p, q, None), (t, q, (x + dx, y + dy), d)]
                else:
                    segs.append((t, p, q, d))
            self.segments = segs
        roots = {}
        for s in {seg[0] for seg in self.segments}:
            x, y = self.pos[s[0]]
            dx, dy = m.outs[s[0]][s]
            roots[s] = (x + dx, y + dy)
        self.trees = routes.build(self.segments, roots)
        # the whole drawing: almost level runs made level, runs moved to better heights (wires.py)
        d = self.drawing()
        self.tidy = {"snapped": wires.snap_level(d) if 'NF034' in self.rules else 0,
                     "moved": wires.tidy(d, self.rules) if self.mode == 'relayout' else 0}
        boxes = [(x, y, x + m.box[n][2], y + m.box[n][3]) for n, (x, y) in self.pos.items()
                 if m.type(n) != 'NodeReroute']
        self.label_pts = routes.place_labels(self.trees, self.m.data.get("labels", []), boxes,
                                             first='NF040' in self.rules, clear='NF041' in self.rules)

    def drawing(self):
        """The routed tree as a wires.Drawing: reroute trees, node boxes, zone and frame outlines."""
        m = self.m
        boxes = {n: (x, y, x + m.box[n][2], y + m.box[n][3]) for n, (x, y) in self.pos.items()
                 if m.type(n) != 'NodeReroute'}
        outlines = []
        for c, _ in self.res.values():
            if c.kind == 'zone':
                inp, out = c.pair
                content = [boxes[n] for n in sorted(c.all) if n in boxes and n not in (inp, out)]
                outlines.append((c.key, wires.zone_outline(boxes.get(inp), boxes.get(out), content)))
        for f in self._frame_rects():
            x0, y0, x1, y1 = f["x"], f["y"], f["x"] + f["w"], f["y"] + f["h"]
            outlines.append((f["name"], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
        return wires.Drawing(self.trees, boxes, outlines)

    def lint(self):
        """Violations of the formatted layout (lint.py), for the enabled rules."""
        from . import lint
        labels = {k: v[1] for k, v in self.label_pts.items()}
        groups = {c.key: set(c.all) for c, _ in self.res.values() if c.kind == 'frame'}
        return lint.lint(self.drawing(), self.rules, labels, groups)

    def _frame_rects(self):
        """Frames as Blender will draw them around their nodes: name, label and box."""
        m = self.m
        frames = []
        for c, res in self.res.values():
            if c.kind == 'frame':
                xs = [self.pos[n][0] for n in c.all] + [self.pos[n][0] + m.box[n][2] for n in c.all]
                ys = [self.pos[n][1] for n in c.all] + [self.pos[n][1] + m.box[n][3] for n in c.all]
                pl, pt, pr, pb = m.pads.get(c.key, (30, 40, 30, 30))
                frames.append({"name": c.key, "label": m.info[c.key]["label"], "x": min(xs) - pl, "y": min(ys) - pt,
                               "w": max(xs) - min(xs) + pl + pr, "h": max(ys) - min(ys) + pt + pb})
        return frames

    def _place(self, c, off):
        """Absolute positions of container c laid out at offset `off`, and its route segments
        (the tags of port pairs exchanged by the parent swapped, see _exchange)."""
        _, res = self.res[id(c)]
        retag = {}
        for ta, tb in self.flipped.get(id(c), ()):
            retag[ta], retag[tb] = tb, ta
        for it in res.items:
            if it.kind in ('node', 'label'):
                self.pos[it.id] = (it.x + off[0], it.y + off[1])
            elif it.kind == 'compound':
                ch = next(ch for ch in c.children if (ch.kind, ch.key) == it.id)
                cres = self.res[id(ch)][1]
                self._place(ch, (it.x + off[0] - cres.origin[0], it.y + off[1] - cres.origin[1]))
        for tag, p, q, dst in res.segments:
            self.segments.append((retag.get(tag, tag), (p[0] + off[0], p[1] + off[1]),
                                  (q[0] + off[0], q[1] + off[1]), self._dst(dst)))

    def _dst(self, dst):
        """The real input socket a route segment ends at (None if the route continues)."""
        if dst is None:
            return None
        item_id, key = dst
        while key[0] == PORT_D:  # a port at a socket of the block's first column
            key = key[2]
        return None if key[0] == PORT_IN else key  # PORT_IN: the route continues inside

    # ------------------------------------------------------------ result as drawn
    def geometry(self):
        """What Blender will show: node boxes, reroute points and links as straight segments
        (socket to socket), with the socket type. Used by tests and the offline metrics."""
        m = self.m
        sc = m.data.get("scale", 1.0)
        # node locations as blend.apply writes them: on the pixel grid of the UI scale
        rnd = lambda v: math.floor(v * sc + 0.5 + 1e-6) / sc
        nodes = []
        for n, (x, y) in self.pos.items():
            _, _, w, h = m.box[n]
            nodes.append({"name": n, "type": m.type(n), "label": m.info[n]["label"], "x": rnd(x), "y": rnd(y),
                          "w": w, "h": h, "src": not any(d[0] == n for _, d, _, _ in self.links),
                          "dupkey": m.info[n].get("dupkey"), "title": m.info[n].get("title"),
                          "socks": [[s["off"][0], s["off"][1], s["type"]] for s in m.info[n].get("socks", {}).values()
                                    if s["vis"]]})
        links = []
        rr = []
        for s, t in self.trees.items():
            typ = m.sock_type[s]
            pts = set(routes.reroute_points(t))
            rr += [{"x": p[0], "y": p[1], "src": list(s), "label": self.label_pts.get((s, p), (None, ""))[1]}
                   for p in pts]
            for p, cs in t.children.items():
                if p != t.root and p not in pts:
                    continue
                for q in cs:
                    if q in t.dst:
                        x, y = self.pos[t.dst[q][0]]
                        dx, dy = m.slot_at(t.dst[q])
                        links.append({"a": list(p), "b": [rnd(x) + dx, rnd(y) + dy], "type": typ,
                                      "src": list(s), "dst": list(t.dst[q][:3]), "rr_a": p != t.root, "rr_b": False,
                                      "multi": len(t.dst[q]) == 4})
                    else:
                        links.append({"a": list(p), "b": list(q), "type": typ, "src": list(s),
                                      "rr_a": p != t.root, "rr_b": True})
        # sockets are placed from the rounded node locations
        for l in links:
            if not l["rr_a"]:
                s = tuple(l["src"])
                x, y = self.pos[s[0]]
                dx, dy = m.outs[s[0]][s]
                l["a"] = [rnd(x) + dx, rnd(y) + dy]
        frames = self._frame_rects()
        zones = [{"name": c.key, "nodes": sorted(c.all)} for c, _ in self.res.values() if c.kind == 'zone']
        return {"nodes": nodes, "reroutes": rr, "links": links, "frames": frames, "zones": zones,
                "swapped": [[v, list(a), list(b)] for v, a, b in self.swapped]}
