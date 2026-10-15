# SPDX-License-Identifier: GPL-3.0-or-later
"""Layout metrics of a drawn tree given as plain geometry (pure Python).

Geometry: {"nodes": [{name, type, x, y, w, h, src, dupkey}], "reroutes": [{x, y}],
"links": [{a: [x, y], b: [x, y], rr_a, rr_b}], "frames": [...]}, y DOWN, node (x, y) = top-left.
"""
GRID = 20.0


def _on_grid(v):
    """True if v is a multiple of GRID."""
    return abs(v / GRID - round(v / GRID)) < 1e-3


def _seg_hits_box(a, b, bx, m=2.0):
    """True if segment a-b passes through the inside of box (x0, y0, x1, y1), shrunk by m."""
    x0, y0, x1, y1 = bx[0] + m, bx[1] + m, bx[2] - m, bx[3] - m
    if x0 >= x1 or y0 >= y1:
        return False
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    return t0 < t1 - 1e-9


def _cross(p1, p2, p3, p4):
    """True if segments p1-p2 and p3-p4 cross at an inner point."""
    def ccw(a, b, c):
        """Signed area of the triangle a, b, c (orientation test)."""
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    return ccw(p3, p4, p1) * ccw(p3, p4, p2) < 0 and ccw(p1, p2, p3) * ccw(p1, p2, p4) < 0


def measure(g, copies=0, swaps=0):
    """Layout metrics of a geometry dict (see the module docstring), with the number of copies and
    swaps of the format that made it."""
    nodes = g["nodes"]
    links = g["links"]
    rr = g["reroutes"]
    R = lambda p: (round(p[0], 1), round(p[1], 1))
    for l in links:
        l["a"], l["b"] = list(R(l["a"])), list(R(l["b"]))
    rr = [{**r, "x": round(r["x"], 1), "y": round(r["y"], 1)} for r in rr]
    segs = [(tuple(l["a"]), tuple(l["b"])) for l in links]
    bent = [l.get("multi", False) for l in links
            if abs(l["a"][1] - l["b"][1]) > 0.5 and abs(l["a"][0] - l["b"][0]) > 0.5]
    curved, curved_multi = bent.count(False), bent.count(True)
    nonortho = len(bent)  # strict: every segment with |dx| > 0.5 and |dy| > 0.5
    backward = sum(1 for a, b in segs if b[0] < a[0] - 0.5 and abs(a[1] - b[1]) <= 0.5)
    crossings = 0
    for i in range(len(segs)):
        for j in range(i + 1, len(segs)):
            s, t = segs[i], segs[j]
            if s[0] in t or s[1] in t:
                continue
            if _cross(s[0], s[1], t[0], t[1]):
                crossings += 1
    boxes = [(n, (n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"])) for n in nodes]
    behind = 0
    for (a, b) in segs:
        for n, bx in boxes:
            if _seg_hits_box(a, b, bx):
                behind += 1
                break
    overlaps = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i][1], boxes[j][1]
            if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1:
                overlaps += 1
    grid = sum(1 for n in nodes if _on_grid(n["x"]) and _on_grid(n["y"]))
    rr_grid = sum(1 for r in rr if _on_grid(r["x"]) and _on_grid(r["y"]))
    # collinear runs: a reroute with one link in and one out, both on one line (does nothing)
    deg_in, deg_out = {}, {}
    for a, b in segs:
        deg_out.setdefault(a, []).append(b)
        deg_in.setdefault(b, []).append(a)
    straight_rr = 0
    for r in rr:
        if r.get("label"):
            continue  # a user's label on a wire
        p = (r["x"], r["y"])
        ins, outs = deg_in.get(p, []), deg_out.get(p, [])
        if len(ins) == 1 and len(outs) == 1:
            a, b = ins[0], outs[0]
            if ((abs(a[1] - p[1]) < 0.5 and abs(b[1] - p[1]) < 0.5)
                    or (abs(a[0] - p[0]) < 0.5 and abs(b[0] - p[0]) < 0.5)):
                straight_rr += 1
    # source nodes: longest route (along the drawn links) to a real consumer
    far, far_node = 0.0, None
    for n in nodes:
        if not n.get("dupkey"):
            continue
        starts = [l for l in links if l.get("src", [None])[0] == n["name"] or l.get("from") == n["name"]]
        starts = [l for l in starts if not l["rr_a"]]
        best = 0.0
        stack = [(tuple(l["b"]), abs(l["a"][0] - l["b"][0]) + abs(l["a"][1] - l["b"][1]), l["rr_b"]) for l in starts]
        seen = 0
        while stack and seen < 5000:
            seen += 1
            p, d, more = stack.pop()
            if not more:
                best = max(best, d)
                continue
            for q in deg_out.get(p, []):
                lk = next((l for l in links if tuple(l["a"]) == p and tuple(l["b"]) == q), None)
                stack.append((q, d + abs(p[0] - q[0]) + abs(p[1] - q[1]), lk["rr_b"] if lk else False))
        if best > far:
            far, far_node = best, n["name"]
    # nodes whose top or bottom is level with a node beside them (to the left or right)
    level = 0
    for a in nodes:
        for b in nodes:
            if a is b or not (b["x"] >= a["x"] + a["w"] or a["x"] >= b["x"] + b["w"]):
                continue
            if abs(a["x"] - b["x"]) > 600:
                continue
            if abs(a["y"] - b["y"]) < 0.5 or abs(a["y"] + a["h"] - b["y"] - b["h"]) < 0.5:
                level += 1
                break
    xs = [n["x"] for n in nodes] + [n["x"] + n["w"] for n in nodes]
    ys = [n["y"] for n in nodes] + [n["y"] + n["h"] for n in nodes]
    ends = _ends(links)
    wf = wire_faults([(r["x"], r["y"]) for r in rr],
                     [(tuple(l["a"]), tuple(l["b"]), tuple(l.get("src") or [l.get("from")]),
                       not l["rr_a"], not l["rr_b"], ends[k], tuple(l["dst"]) if l.get("multi") else None)
                      for k, l in enumerate(links)])
    st, tot = straight_links(links)
    wf["label_overlap"] = label_overlaps([(r["x"], r["y"], r["label"]) for r in rr if r.get("label")])
    return {**wf, "straight": f"{st}/{tot}", "nonortho": nonortho, "curved": curved, "curved_multi": curved_multi,
            "behind": behind, "crossings": crossings, "overlaps": overlaps, "backward": backward,
            "nodes_on_grid": f"{grid}/{len(nodes)}", "level": f"{level}/{len(nodes)}",
            "rr_on_grid": f"{rr_grid}/{len(rr)}", "src_far": round(far), "src_far_node": far_node,
            "duplicates": copies, "swaps": swaps, "reroutes": len(rr), "useless_rr": straight_rr, "links": len(links),
            "size": f"{round(max(xs) - min(xs))}x{round(max(ys) - min(ys))}"}


RR_CLEAR = 10.0    # two reroutes closer than this look like one (overlapping reroutes)
ON_WIRE = 6.0      # a reroute this close to a wire it does not end looks like a junction on it
NEAR_RR = 10.0     # a crossing this close to a reroute or bend is not clean
NEAR_SOCK = 20.0   # a crossing this close to a node's socket is not clean


def _pt_seg(p, a, b):
    """Distance from point p to segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    x, y = a[0] + t * dx, a[1] + t * dy
    return ((p[0] - x) ** 2 + (p[1] - y) ** 2) ** 0.5


def _intersection(a, b, c, d):
    """Intersection point of segments a-b and c-d (assumed to cross)."""
    x1, y1, x2, y2, x3, y3, x4, y4 = a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def wire_faults(rr, segs):
    """Faults of the drawn wires, shared by the offline and the Blender metrics.

    rr: reroute points [(x, y)]. segs: drawn links [(a, b, src, a_is_socket, b_is_socket, ends, multi)]:
    src names the source socket (links of one source may share points); ends (optional) is
    (source node, destination nodes the link leads to); multi (optional) names the multi-input
    socket the link enters (its links run a slot apart, which is not a fault). Returns a dict:
      rr_overlap  pairs of reroutes closer than RR_CLEAR
      rr_on_wire  reroutes lying on a link they do not end
      cross_clean crossings of a horizontal and a vertical link away from bends and sockets
      cross_other every other crossing
      collinear   pairs of links of different sources on (or right next to) one line
      cross_bundle crossings of links that leave or enter the same node
      marks       fault positions, for debugging pictures
    """
    rr = [(round(p[0], 1), round(p[1], 1)) for p in rr]
    overlap = 0
    for i in range(len(rr)):
        for j in range(i + 1, len(rr)):
            if (abs(rr[i][0] - rr[j][0]) < RR_CLEAR and abs(rr[i][1] - rr[j][1]) < RR_CLEAR and
                    ((rr[i][0] - rr[j][0]) ** 2 + (rr[i][1] - rr[j][1]) ** 2) ** 0.5 < RR_CLEAR):
                overlap += 1
    multi = lambda s: s[6] if len(s) > 6 else None
    corner = {}  # reroute point -> the multi-input socket its last run enters
    for s in segs:
        if multi(s) is not None:
            corner[(round(s[0][0], 1), round(s[0][1], 1))] = multi(s)
    on_wire = 0
    for p in rr:
        for s in segs:
            a, b = s[:2]
            if _close(p, a) or _close(p, b):
                continue
            if multi(s) is not None and corner.get(p) == multi(s):
                continue
            if _pt_seg(p, a, b) < ON_WIRE:
                on_wire += 1
                break
    clean = other = bundle = 0
    marks = []
    for i in range(len(segs)):
        a, b, sa, ka, kb = segs[i][:5]
        for j in range(i + 1, len(segs)):
            c, d, sc, kc, kd = segs[j][:5]
            if sa == sc or not _cross(a, b, c, d):
                continue
            if len(segs[i]) > 5 and len(segs[j]) > 5:
                (n1, d1), (n2, d2) = segs[i][5], segs[j][5]
                if n1 == n2 or d1 & d2:
                    bundle += 1
                    marks.append(_intersection(a, b, c, d) + ("bundle",))
            x = _intersection(a, b, c, d)
            h1, v1 = abs(a[1] - b[1]) < 0.5, abs(a[0] - b[0]) < 0.5
            h2, v2 = abs(c[1] - d[1]) < 0.5, abs(c[0] - d[0]) < 0.5
            ok = (h1 and v2) or (v1 and h2)
            for p, sock in ((a, ka), (b, kb), (c, kc), (d, kd)):
                if _dist(p, x) < (NEAR_SOCK if sock else NEAR_RR):
                    ok = False
            if ok and any(_dist(p, x) < NEAR_RR for p in rr):
                ok = False
            if ok:
                clean += 1
            else:
                other += 1
                marks.append(x + ("other",))
    collinear = 0
    for i in range(len(segs)):
        a, b, sa = segs[i][:3]
        for j in range(i + 1, len(segs)):
            c, d, sc = segs[j][:3]
            if sa == sc or (multi(segs[i]) is not None and multi(segs[i]) == multi(segs[j])):
                continue
            if abs(a[1] - b[1]) < 0.5 and abs(c[1] - d[1]) < 0.5 and abs(a[1] - c[1]) < 6.0:
                lo, hi = max(min(a[0], b[0]), min(c[0], d[0])), min(max(a[0], b[0]), max(c[0], d[0]))
            elif abs(a[0] - b[0]) < 0.5 and abs(c[0] - d[0]) < 0.5 and abs(a[0] - c[0]) < 6.0:
                lo, hi = max(min(a[1], b[1]), min(c[1], d[1])), min(max(a[1], b[1]), max(c[1], d[1]))
            else:
                continue
            if hi - lo > 1.0:
                collinear += 1
    return {"rr_overlap": overlap, "rr_on_wire": on_wire, "cross_clean": clean, "cross_other": other,
            "collinear": collinear, "cross_bundle": bundle, "marks": marks}


def _dist(p, q):
    """Euclidean distance."""
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _close(p, q):
    """True if two points are the same (within rounding)."""
    return abs(p[0] - q[0]) < 0.6 and abs(p[1] - q[1]) < 0.6


def straight_links(links):
    """(straight, total): links from a source socket to an input socket whose whole drawn route
    (through reroutes) is one horizontal line. links: [{a, b, rr_a, rr_b}] as in measure()."""
    into = {}
    for l in links:
        if l["rr_b"]:
            into[tuple(l["b"])] = l
    total = straight = 0
    for l in links:
        if l["rr_b"]:
            continue
        total += 1
        ok, cur, n = True, l, 0
        while ok and n < 1000:
            n += 1
            if abs(cur["a"][1] - cur["b"][1]) > 0.5:
                ok = False
            if not cur["rr_a"]:
                break
            cur = into.get(tuple(cur["a"]))
            if cur is None:
                break
        straight += ok
    return straight, total


def label_box(x, y, text):
    """Box of a reroute label as Blender draws it: centred above the dot (labels.box)."""
    from . import labels
    return labels.box((x, y), labels.text_width(text))


def label_overlaps(labels):
    """Pairs of reroute labels [(x, y, text)] whose text boxes overlap."""
    boxes = [label_box(*l) for l in labels]
    n = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                n += 1
    return n


def _ends(links):
    """For each drawn link: (source node, destination nodes it leads to through reroutes)."""
    out_of = {}
    for k, l in enumerate(links):
        out_of.setdefault((tuple(l.get("src") or [l.get("from")]), tuple(l["a"])), []).append(k)
    memo = {}

    def dsts(k):
        """Destination nodes that drawn link k leads to."""
        if k in memo:
            return memo[k]
        memo[k] = frozenset()
        l = links[k]
        src = tuple(l.get("src") or [l.get("from")])
        if not l["rr_b"]:
            d = l.get("dst") or [l.get("to")]
            res = frozenset([d[0]])
        else:
            res = frozenset().union(*[dsts(j) for j in out_of.get((src, tuple(l["b"])), [])])
        memo[k] = res
        return res
    return [((l.get("src") or [l.get("from")])[0], dsts(k)) for k, l in enumerate(links)]
