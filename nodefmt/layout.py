# SPDX-License-Identifier: GPL-3.0-or-later
"""Lay out a whole tree (pure Python): containers (zones, frames) inside out, then absolute
positions and reroute routes. Works on a model.Model; blend.py writes the result to Blender."""
import math

from . import engine, routes, rules as _rules, wires

PORT_D = engine.PORT_DIRECT  # border port at a socket of a first-column item
PORT_IN = '<port:in>'     # border port on the container's left edge
GROUP_OUTPUT = 'NodeGroupOutput'
# nodes that take the last column of the tree (the Group Output first: it anchors the layout)
OUTPUTS = (GROUP_OUTPUT, 'ShaderNodeOutputMaterial', 'ShaderNodeOutputWorld', 'ShaderNodeOutputLight',
           'ShaderNodeOutputAOV', 'ShaderNodeOutputLineStyle', 'CompositorNodeViewer', 'CompositorNodeOutputFile')


class Container:
    """A part of the tree laid out as one block: the root, a zone (input, output and everything
    between) or a frame. `all` holds its nodes, `direct` the ones not in a child container."""
    def __init__(self, kind, key, nodes):
        """A container of `kind` ('root', 'zone', 'frame') named `key`."""
        self.kind, self.key, self.all = kind, key, set(nodes)
        self.children = []
        self.parent = None
        self.direct = set()


def containers(m):
    """Zones and frames that can be laid out as one block, nested as a tree."""
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
    # pure sources (nothing linked in) used only inside one zone go into it
    has_in = {d[0] for _, d, _, _ in m.links}
    for n in m.real:
        if n in has_in or any(n in z.all for z in zones):
            continue
        cons = succ.get(n, set())
        if not cons:
            continue
        for z in zones:
            if cons <= z.all - {z.pair[0]}:  # a node feeding the zone input stays outside
                z.all.add(n)
                break
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
    return kept


def nest(m, conts):
    """Nest the containers into a tree under a root; returns (root, {node: innermost container})."""
    root = Container('root', None, set(m.real))
    allc = [root] + conts

    def contains(a, b):  # a strictly contains b
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
    trees and labels. run() does it all; the result is read by blend.apply.

    Snapshots (for animations of the algorithm, see tools/animate.py): with record=True, self.snapshots gets
    plain-data states in order: 'direct' (the nodes where they were, every link drawn direct
    from socket to socket, no reroutes), then for each container the engine phases (orders,
    seeds, search, slide; see engine.snapshot_state, in the container's own coordinates), then
    'final' (geometry(): nodes, reroutes and links as Blender will draw them). The original
    drawing with its reroutes is not part of the model; take it from the tree (tools/dump_tree.py)."""

    def __init__(self, m, mode='relayout', swaps=True, record=False, rules=None):
        """Format model m in `mode` ('relayout' or 'keep'); swaps=False keeps commutative inputs as
        they are; record=True keeps snapshots of the phases; rules: the enabled rule codes
        (rules.py; default all)."""
        self.snapshots = [] if record else None
        self.m = m
        self.mode = mode
        self.rules = frozenset(rules if rules is not None else _rules.DEFAULT)
        self.swaps_on = swaps and 'NF011' in self.rules
        self.loose_frames = set()
        self.swapped = []  # (node, gid a, gid b): links of a commutative pair exchanged

    def run(self):
        """Lay out the tree (run_steps() in one go). Returns self."""
        for _ in self.run_steps():
            pass
        return self

    def run_steps(self):
        """Lay out the tree, as a generator: yields ('layout', k, n) after each of the n
        containers (zones, frames, the tree itself; again with the same k when a zone's output
        mode is tried), then ('routing', 1, 1) once the routes are placed. A frame that would
        form a cycle as one block is laid out as loose nodes (the count starts again)."""
        if self.snapshots is not None:
            self.snapshots.append({"phase": "direct", **self._direct()})
        while True:
            conts = [c for c in containers(self.m) if not (c.kind == 'frame' and c.key in self.loose_frames)]
            self.root, self.home = nest(self.m, conts)
            try:
                self.res, self.node_items, self.comp_items = {}, {}, {}
                self.ctx, self.applied, self.port_of = {}, {}, {}
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
        self.place(self.root)
        yield ('routing', 1, 1)
        if self.snapshots is not None:
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
            ds, dd = m.outs[s[0]][s], m.ins[d[0]][m.slot_key(s, d, sid)]
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
        """Lay out container c (children first): build its items and edges, ports for links that
        cross its border, run the engine, and make it one compound item of its parent. A child
        zone may offer other heights for its output (engine: zone output modes); c tries each and
        keeps the one that makes c and the child cheapest together, so a lowered zone output is
        only kept when what follows the zone fits better too. A generator (see run_steps)."""
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
        for v, a, b in self.applied.pop(id(c), []):
            self._unswap(v, a, b)
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
            if name in m.comm and self.swaps_on:
                it.comm = m.comm[name]
            if pin and c.kind == 'zone':  # zone input/output: their items, to put them on one line
                side = m.outs if pin == 'first' else m.ins
                it.zmatch = {m.info[g[0]]["socks"][f"{g[1]}{g[2]}"]["id"]: g for g in side[name] if len(g) == 3}
                it.zgeo = {k: m.geo[g] for k, g in it.zmatch.items()}
            self.node_items[name] = it
            items.append(it)
        for ch in c.children:
            items.append(self.comp_items[id(ch)])
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
                bk = d if b.kind in ('node', 'label') else b.port_of[(s, d)]
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
        port_of, ports_in, ports_out = {}, {}, {}
        direct_in, direct_out = {}, {}
        all_edges = list(edges.values())
        for s, d in b_in:
            b = self.item_of(c, d[0])
            bk = d if b.kind in ('node', 'label') else b.port_of[(s, d)]
            if b.rank == 0:
                key = (PORT_D, b.id, bk)
                port_of[(s, d)] = key
                direct_in[key] = (b, bk)
                if b.kind == 'node':
                    b.comm = None  # fed from outside: the parent level owns this link
            else:
                key = (PORT_IN, s)
                port_of[(s, d)] = key
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
        res = engine.layout(items, all_edges, self.mode, pad, self._recorder(c))
        self.ctx[id(c)] = (port_of, ports_in, direct_in, ports_out, direct_out)
        self._apply(c, res)

    def _apply(self, c, res):
        """Make res the layout of container c: its input swaps applied to the links."""
        port_of = self.ctx[id(c)][0]
        for v, a, b in res.swapped:
            self._swap(v, a, b)
            port_of = {(s, b if d == a else a if d == b else d): k for (s, d), k in port_of.items()}
        self.applied[id(c)] = list(res.swapped)
        self.port_of[id(c)] = port_of
        self.res[id(c)] = (c, res)

    def _use_alt(self, c, mode):
        """Switch zone container c to its layout for zone output `mode` (see layout())."""
        for v, a, b in self.applied.pop(id(c), []):
            self._unswap(v, a, b)
        self._apply(c, self.res[id(c)][1].realize(mode))
        self._compound(c)

    def _compound(self, c):
        """Container c as one compound item of its parent: its box and the ports where links
        cross its border."""
        m = self.m
        res = self.res[id(c)][1]
        _, ports_in, direct_in, ports_out, direct_out = self.ctx[id(c)]
        port_of = self.port_of[id(c)]
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
        nodes = [m.box[n] for n in c.all]
        comp = engine.Item((c.kind, c.key), 'compound', res.w, res.h, ins, outs,
                           min(b[0] for b in nodes), min(b[1] for b in nodes))
        comp.port_of = port_of
        comp.geo_out = any(m.geo.get(s, False) for s in outs)
        comp.res = res
        comp.big = res.ranks >= 3
        # main input: the zone input's main socket, else a geometry port, else the top port
        main = None
        if c.kind == 'zone':
            mk = m.main.get(c.pair[0])
            for key in ins:
                if key[0] == PORT_D and key[2] == mk:
                    main = key
        if main is None and ins:
            main = min(ins, key=lambda k: (not self._port_geo(k), ins[k][1]))
        comp.main_in = main
        self.comp_items[id(c)] = comp

    def _unswap(self, v, a, b):
        """Undo an exchange made by _swap (an exchange is its own inverse)."""
        self._swap(v, a, b)
        self.swapped.remove((v, a, b))
        self.swapped.remove((v, a, b))

    def _swap(self, v, a, b):
        """The engine exchanged the links of inputs a and b of node v."""
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
    def place(self, root):
        """Absolute positions: every container's local layout shifted to where its block sits."""
        m = self.m
        self.pos, self.segments = {}, []
        self._place(root, (0.0, 0.0))
        # keep the tree where it was: the Group Output (else an output node such as the Material
        # Output, else the first node by name) does not move, so formatting a formatted tree
        # changes nothing
        outs = sorted((n for n in self.pos if m.type(n) in OUTPUTS), key=lambda n: (OUTPUTS.index(m.type(n)), n))
        outs = outs or sorted(self.pos)
        ref = outs[0]
        self.anchor = ref
        bx, by = m.box[ref][0], m.box[ref][1]
        px, py = self.pos[ref]
        off = (bx - px, by - py)  # exactly: two equal layouts land on the same spot
        self.pos = {k: (x + off[0], y + off[1]) for k, (x, y) in self.pos.items()}
        self.segments = [(t, (p[0] + off[0], p[1] + off[1]), (q[0] + off[0], q[1] + off[1]), d)
                         for t, p, q, d in self.segments]
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
                                             first='NF040' in self.rules)

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
        """Absolute positions of container c laid out at offset `off`, and its route segments."""
        _, res = self.res[id(c)]
        for it in res.items:
            if it.kind in ('node', 'label'):
                self.pos[it.id] = (it.x + off[0], it.y + off[1])
            elif it.kind == 'compound':
                ch = next(ch for ch in c.children if (ch.kind, ch.key) == it.id)
                cres = self.res[id(ch)][1]
                self._place(ch, (it.x + off[0] - cres.origin[0], it.y + off[1] - cres.origin[1]))
        for tag, p, q, dst in res.segments:
            self.segments.append((tag, (p[0] + off[0], p[1] + off[1]), (q[0] + off[0], q[1] + off[1]),
                                  self._dst(dst)))

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
                        dx, dy = m.ins[t.dst[q][0]][t.dst[q]]
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
