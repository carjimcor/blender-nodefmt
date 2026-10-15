# SPDX-License-Identifier: GPL-3.0-or-later
"""Layout metrics of a drawn node tree (call draw.Editor.show(tree) first)."""
import bpy

from . import ortho
from .measure import label_overlaps, wire_faults
from .sockets import socket_location

GRID = 20.0


def _box(n, ui):
    """Box (x0, y0, x1, y1) of a node in node units, y up; a reroute is a small square."""
    x, y = n.location_absolute
    if n.bl_idname == 'NodeReroute':
        return x - 6, y - 6, x + 6, y + 6
    return x, y - n.dimensions.y / ui, x + n.dimensions.x / ui, y


def _cross(p1, p2, p3, p4):
    """True if segments p1-p2 and p3-p4 cross at an inner point."""
    def ccw(a, b, c):
        """Signed area of the triangle a, b, c (orientation test)."""
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p3, p4, p1) * ccw(p3, p4, p2) < 0 and ccw(p1, p2, p3) * ccw(p1, p2, p4) < 0


def link_end(l):
    """Where a link meets its input socket (multi-input slots spread as Blender draws them)."""
    return ortho.link_end(l, ortho.slot_gap())


def _source(l):
    """The real output socket feeding a link, through reroutes (None if dangling)."""
    for _ in range(1000):
        if l.from_node.bl_idname != 'NodeReroute':
            return (l.from_node.name, l.from_socket.identifier)
        ins = l.from_node.inputs[0].links
        if not ins:
            return None
        l = ins[0]
    return None


def _targets(l, depth=0):
    """Real nodes a link leads to, through reroutes."""
    if l.to_node.bl_idname != 'NodeReroute':
        return {l.to_node.name}
    if depth > 500:
        return set()
    out = set()
    for k in l.to_node.outputs[0].links:
        out |= _targets(k, depth + 1)
    return out


def wires(nt, links):
    """Wire faults (see measure.wire_faults), label overlaps and straight links, y down."""
    def down(p):
        """A point with y down, as in the layout model."""
        return (p[0], -p[1])
    rr = [n for n in nt.nodes if n.bl_idname == 'NodeReroute']
    segs = [(down(socket_location(l.from_socket)), down(link_end(l)), _source(l),
             l.from_node.bl_idname != 'NodeReroute', l.to_node.bl_idname != 'NodeReroute',
             ((_source(l) or ("?",))[0], frozenset(_targets(l))),
             (l.to_node.name, l.to_socket.identifier) if l.to_socket.is_multi_input else None) for l in links]
    res = wire_faults([down(r.location_absolute) for r in rr], segs)
    res.pop("marks")
    res["label_overlap"] = label_overlaps([(r.location_absolute.x, -r.location_absolute.y, r.label)
                                           for r in rr if r.label])
    total = straight = 0
    for l in links:
        if l.to_node.bl_idname == 'NodeReroute':
            continue
        total += 1
        ok, cur = True, l
        for _ in range(1000):
            if abs(socket_location(cur.from_socket)[1] - link_end(cur)[1]) > 0.5:
                ok = False
                break
            if cur.from_node.bl_idname != 'NodeReroute' or not cur.from_node.inputs[0].links:
                break
            cur = cur.from_node.inputs[0].links[0]
        straight += ok
    res["straight_links"] = f"{straight}/{total}"
    res["labelled_rr"] = sum(1 for r in rr if r.label)
    return res


def measure(nt):
    """Layout metrics of a drawn tree (call draw.Editor.show first); see measure.wire_faults."""
    ui = bpy.context.preferences.system.ui_scale
    links = [l for l in nt.links if not l.is_hidden
             and not l.from_node.hide and not l.to_node.hide and l.to_node.bl_idname != 'NodeFrame']
    segs = [(socket_location(l.from_socket), link_end(l)) for l in links]
    horiz = sum(abs(a[1] - b[1]) <= 0.5 for a, b in segs)
    bent = [l.to_socket.is_multi_input for l, (a, b) in zip(links, segs)
            if abs(a[1] - b[1]) > 0.5 and abs(a[0] - b[0]) > 0.5]
    curved, curved_multi = bent.count(False), bent.count(True)  # into a multi-input socket: on purpose
    vert = sum(abs(a[0] - b[0]) <= 0.5 and abs(a[1] - b[1]) > 0.5 for a, b in segs)
    crossings = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            s, t = segs[i], segs[j]
            if s[0] in t or s[1] in t:
                continue
            if _cross(s[0], s[1], t[0], t[1]):
                crossings += 1
    real = [n for n in nt.nodes if n.bl_idname not in ('NodeFrame', 'NodeReroute')]
    boxes = [(n, _box(n, ui)) for n in real]
    through, through_pairs = 0, []
    for l, (a, b) in zip(links, segs):
        for n, bx in boxes:
            if n in (l.from_node, l.to_node):
                continue
            if max(a[0], b[0]) < bx[0] or min(a[0], b[0]) > bx[2] or max(a[1], b[1]) < bx[1] or min(a[1], b[1]) > bx[3]:
                continue
            for k in range(1, 40):
                t = k / 40
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                if bx[0] + 2 < x < bx[2] - 2 and bx[1] + 2 < y < bx[3] - 2:
                    through += 1
                    through_pairs.append((l.from_node.name, l.to_node.name, n.name))
                    break
    overlaps, pairs = 0, []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i][1], boxes[j][1]
            if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                overlaps += 1
                pairs.append((boxes[i][0].name, boxes[j][0].name))
    # main inputs (first linked geometry input, else first linked input) reached by a horizontal link
    main_total = main_straight = 0
    for n in real:
        ins = [s for s in n.inputs if s.is_linked and s.enabled and not s.hide]
        if not ins or n.hide:
            continue
        geo = [s for s in ins if s.type == 'GEOMETRY']
        s = (geo or ins)[0]
        l = s.links[0]
        if l.is_hidden or l.from_node.hide:
            continue
        main_total += 1
        a, b = socket_location(l.from_socket), link_end(l)
        main_straight += abs(a[1] - b[1]) <= 0.5
    on_grid_x = sum(abs(n.location_absolute.x / GRID - round(n.location_absolute.x / GRID)) < 1e-3 for n in real)
    on_grid = sum(all(abs(v / GRID - round(v / GRID)) < 1e-3 for v in n.location_absolute) for n in real)
    rr = [n for n in nt.nodes if n.bl_idname == 'NodeReroute']
    # chains of 3+ reroutes on one line where the middle ones pass straight through (no tap)
    chains = 0
    for r in rr:
        if r.label or len(r.outputs[0].links) != 1 or not r.inputs[0].links:
            continue
        a = r.inputs[0].links[0].from_node
        b = r.outputs[0].links[0].to_node
        if a.bl_idname != 'NodeReroute' or b.bl_idname != 'NodeReroute':
            continue
        pa, pr, pb = a.location_absolute, r.location_absolute, b.location_absolute
        if (abs(pa.y - pr.y) < 0.5 and abs(pb.y - pr.y) < 0.5) or (abs(pa.x - pr.x) < 0.5 and abs(pb.x - pr.x) < 0.5):
            chains += 1
    useless = sum(1 for r in rr if not r.label and len(r.outputs[0].links) == 1 and r.inputs[0].links
                  and _straight_through(r))
    rr_grid = sum(all(abs(v / GRID - round(v / GRID)) < 1e-3 for v in r.location_absolute) for r in rr)
    # source nodes (nothing linked in): longest path, along the drawn links, to a real consumer
    def reach(sock, dist, out):
        """Route lengths from output socket `sock` to every real node it feeds, through reroutes."""
        for l in sock.links:
            a, b = socket_location(l.from_socket), socket_location(l.to_socket)
            d = dist + abs(a[0] - b[0]) + abs(a[1] - b[1])
            if l.to_node.bl_idname == 'NodeReroute':
                reach(l.to_node.outputs[0], d, out)
            else:
                out.append(d)
    far, far_node = 0.0, None
    from .dup import duplicable
    for n in real:
        if not duplicable(n):
            continue
        ds = []
        for o in n.outputs:
            reach(o, 0.0, ds)
        if ds and max(ds) > far:
            far, far_node = max(ds), n.name
    allb = [b for _, b in boxes]
    return {
        **wires(nt, links),
        # strict: every drawn segment neither horizontal nor vertical (ortho.TOL), fans included
        "nonortho": ortho.count(nt),
        "links": len(links),
        "straight": horiz,
        "curved": curved,
        "curved_multi": curved_multi,
        "vertical": vert,
        "main_straight": f"{main_straight}/{main_total}",
        "crossings": crossings,
        "through_node": through,
        "through_pairs": through_pairs[:4],
        "overlaps": overlaps,
        "overlap_pairs": pairs[:5],
        "grid_x": f"{on_grid_x}/{len(real)}",
        "grid_xy": f"{on_grid}/{len(real)}",
        "reroutes": len(rr),
        "rr_grid": f"{rr_grid}/{len(rr)}",
        "src_far": round(far),
        "src_far_node": far_node,
        "collinear3": chains,
        "useless_rr": useless,
        "size": (f"{round(max(b[2] for b in allb) - min(b[0] for b in allb))}x"
                 f"{round(max(b[3] for b in allb) - min(b[1] for b in allb))}"),
    }


def _straight_through(r):
    """A reroute whose in- and out-links continue in the same direction (it does nothing)."""
    a = socket_location(r.inputs[0].links[0].from_socket)
    b = socket_location(r.outputs[0].links[0].to_socket)
    p = r.location_absolute
    return (abs(a[1] - p.y) < 0.5 and abs(b[1] - p.y) < 0.5 and (a[0] - p.x) * (b[0] - p.x) < 0) or \
           (abs(a[0] - p.x) < 0.5 and abs(b[0] - p.x) < 0.5 and (a[1] - p.y) * (b[1] - p.y) < 0)


def drawing(nt, data=None):
    """(wires.Drawing of the tree as Blender draws it, for lint.py; reroute labels {(source,
    point): text}; frames {frame: nodes}). data: model.read(nt) if the caller has it. Call
    Editor.show first."""
    from . import model, routes, wires
    from .layout import containers
    ui = bpy.context.preferences.system.ui_scale
    data = data or model.read(nt)
    m = model.Model(data)
    down = lambda p: routes._r((p[0], -p[1]))
    trees, labels = {}, {}
    for l in nt.links:
        if l.is_hidden or l.to_node.bl_idname == 'NodeFrame' or l.from_node.bl_idname == 'NodeFrame':
            continue
        src = _source_gid(l)
        if src is None:
            continue
        t = trees.get(src)
        if t is None:
            t = trees[src] = routes.Tree(src)
            n = nt.nodes[src[0]]
            t.root = down(socket_location(n.outputs[src[2]]))
        a = t.root if l.from_node.bl_idname != 'NodeReroute' else down(l.from_node.location_absolute)
        if l.to_node.bl_idname == 'NodeReroute':
            b = down(l.to_node.location_absolute)
            if l.to_node.label:
                labels[(src, b)] = l.to_node.label
        else:
            b = down(link_end(l))
            key = model.gid_of(l.to_socket)
            if l.to_socket.is_multi_input:
                ids = sorted(k.multi_input_sort_id for k in l.to_socket.links)
                key = key + (ids.index(l.multi_input_sort_id),)
            t.dst[b] = key
        t.children.setdefault(a, set()).add(b)
        t.children.setdefault(b, set())
    for t in trees.values():
        routes._fix_parents(t)
    boxes = {}
    for n in nt.nodes:
        if n.bl_idname in ('NodeFrame', 'NodeReroute'):
            continue
        x, y = n.location_absolute
        boxes[n.name] = (x, -y, x + n.dimensions.x / ui, -y + n.dimensions.y / ui)
    outlines, groups = [], {}
    for c in containers(m):
        if c.kind == 'zone':
            inp, out = c.pair
            content = [boxes[k] for k in sorted(c.all) if k in boxes and k not in (inp, out)]
            outlines.append((c.key, wires.zone_outline(boxes.get(inp), boxes.get(out), content)))
        else:
            f = nt.nodes[c.key]
            x, y = f.location_absolute
            x0, y0, x1, y1 = x, -y, x + f.dimensions.x / ui, -y + f.dimensions.y / ui
            outlines.append((c.key, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
            groups[c.key] = set(c.all)
    return wires.Drawing(trees, boxes, outlines), labels, groups


def _source_gid(l):
    """The gid of the real output socket feeding a link, through reroutes (None if dangling)."""
    from .model import gid_of
    for _ in range(1000):
        if l.from_node.bl_idname != 'NodeReroute':
            return gid_of(l.from_socket)
        ins = l.from_node.inputs[0].links
        if not ins:
            return None
        l = ins[0]
    return None
