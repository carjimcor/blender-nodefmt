# SPDX-License-Identifier: GPL-3.0-or-later
"""A node tree as plain data, so the layout can run (and be tested) without Blender.

`read(nt)` turns a drawn tree into a JSON-able dict; `Model(data)` derives what the layout needs.
Coordinates: y is DOWN (y = -blender_y). A socket is a gid (node name, 'i' | 'o', index).
"""

import math

FRAME = "NodeFrame"
SLOT = 5.0  # distance between the links of a multi-input socket at UI scale 1 (Blender's
#              NODE_MULTI_INPUT_LINK_GAP, a quarter widget unit); data["slot"] has the drawn one
REROUTE = "NodeReroute"

# commutative nodes: node type -> the operations whose two inputs may be swapped (None: any)
COMMUTATIVE = {
    "ShaderNodeMath": {"ADD", "MULTIPLY", "MINIMUM", "MAXIMUM"},
    "FunctionNodeIntegerMath": {"ADD", "MULTIPLY", "MINIMUM", "MAXIMUM"},
    "FunctionNodeBooleanMath": {"AND", "OR", "XOR", "NAND", "NOR"},
    "ShaderNodeVectorMath": {"ADD", "MULTIPLY"},
    "FunctionNodeCompare": {"EQUAL", "NOT_EQUAL"},
    "ShaderNodeAddShader": None,  # no operation: always (Mix Shader is not: its Fac picks a side)
}
FLOW = ("GEOMETRY", "SHADER")  # socket types of the main flow, lined up first


def gid_of(s):
    """The gid of a socket: (node name, 'i' | 'o', index)."""
    n = s.node
    if s.is_output:
        return (n.name, "o", list(n.outputs).index(s))
    return (n.name, "i", list(n.inputs).index(s))


def comm_pair(n):
    """Indices of the two inputs of a node that may be swapped, or None."""
    if n.bl_idname not in COMMUTATIVE:
        return None
    ops = COMMUTATIVE[n.bl_idname]
    if ops is not None and getattr(n, "operation", None) not in ops:
        return None
    vis = [k for k, s in enumerate(n.inputs) if s.enabled and not s.hide]
    if n.bl_idname == "FunctionNodeCompare":
        a = [k for k in vis if n.inputs[k].name == "A"]
        b = [k for k in vis if n.inputs[k].name == "B"]
        if len(a) != 1 or len(b) != 1 or n.inputs[a[0]].type != n.inputs[b[0]].type:
            return None
        return (a[0], b[0])
    if len(vis) < 2 or vis[0] != 0 or vis[1] != 1:
        return None
    return (0, 1)


def _same_default(a, b):
    """True if two sockets hold the same stored value."""
    va, vb = getattr(a, "default_value", None), getattr(b, "default_value", None)
    try:
        va, vb = tuple(va), tuple(vb)
    except TypeError:
        pass
    return va == vb


def read(nt, where=None, part=None, pins=None):
    """Plain data of a drawn tree (call draw.Editor.show(nt) first). where: {name: location} to
    record instead of the drawn one, for nodes moved to be measured (api.read_tree); socket
    offsets always come from where the nodes are drawn now.

    part: read only these node names and the links between them (Sort Selection, part.py).
    pins: {reroute name: 'first' | 'last'}, reroutes of the part standing for its links to the
    rest; they are kept and take the first or last column."""
    where = where or {}
    pins = pins or {}
    from . import dup, ortho
    from .labels import text_width
    from .sockets import socket_location, verify

    verify(nt)
    ui = ortho.ui_scale()
    nodes = [n for n in nt.nodes if part is None or n.name in part]
    # reroutes to remove and rebuild; labels go back on the new routes (routes.place_labels)
    removable = {n.name for n in nodes if n.bl_idname == REROUTE and n.name not in pins}
    bad = [lk for lk in nt.links if lk.is_hidden]
    todo = [n.name for lk in bad for n in (lk.from_node, lk.to_node) if n.name in removable]
    for n in nodes:  # dangling reroutes stay (they are visible as such)
        if n.name in removable and (not n.inputs[0].is_linked or (n.label and not n.outputs[0].is_linked)):
            todo.append(n.name)
    byname = {n.name: n for n in nodes}

    def keep(todo):
        """Mark reroutes as kept (not removable), and every reroute linked to them."""
        while todo:
            name = todo.pop()
            if name not in removable:
                continue
            removable.discard(name)
            r = byname[name]
            for lk in list(r.inputs[0].links) + list(r.outputs[0].links):
                for m in (lk.from_node, lk.to_node):
                    if m.name in removable:
                        todo.append(m.name)

    def back(lk):
        """The real sources of link l through removable reroutes: [(socket, chain of links)]."""
        n = lk.from_node
        if n.name not in removable:
            return [(lk.from_socket, [lk])]
        res = []
        for k in n.inputs[0].links:
            res += [(s, chain + [lk]) for s, chain in back(k)]
        return res

    def label_info(n):
        """Sources, destinations and depth (reroutes upstream) of a labelled reroute."""
        srcs = {gid_of(s) for lk in n.inputs[0].links for s, _ in back(lk)}
        dsts, todo2, seen = [], [n], set()
        while todo2:
            r = todo2.pop()
            for lk in r.outputs[0].links:
                if lk.is_hidden or lk.to_node.name in seen:
                    continue
                if lk.to_node.name in removable:
                    seen.add(lk.to_node.name)
                    todo2.append(lk.to_node)
                elif lk.to_node.bl_idname != FRAME:
                    dsts.append(gid_of(lk.to_socket))
        depth, r = 0, n
        while r.inputs[0].links and r.inputs[0].links[0].from_node.name in removable:
            depth += 1
            r = r.inputs[0].links[0].from_node
        return srcs, dsts, depth

    keep(todo)
    while True:  # a labelled reroute that does not carry one wire to real sockets stays as it is
        bad = [
            n.name
            for n in nodes
            if n.name in removable and n.label and (len(label_info(n)[0]) != 1 or not label_info(n)[1])
        ]
        if not bad:
            break
        keep(bad)
    labels = []
    for n in nodes:
        if n.name in removable and n.label:
            srcs, dsts, depth = label_info(n)
            x, y = where.get(n.name, n.location_absolute)
            labels.append(
                {
                    "name": n.name,
                    "label": n.label,
                    "src": list(next(iter(srcs))),
                    "x": x,
                    "y": -y,
                    "dsts": sorted(list(d) for d in dsts),
                    "depth": depth,
                    "w": text_width(n.label),
                }
            )

    links = []
    old_routes = {}  # where each link ran before: its reroutes (stability, see engine.py)
    # the sockets of a collapsed panel are all drawn on its header, so links from one source to
    # several of them end at one point: one wire for the layout, the others (twins) are linked
    # with it when the layout is written (blend.apply)
    ends, twins = {}, {}
    inside = {n.name for n in nodes}
    for lk in nt.links:
        if lk.to_node.name in removable or lk.is_hidden or lk.to_node.bl_idname == FRAME:
            continue
        if lk.to_node.name not in inside:
            continue
        for s, chain in back(lk):
            if any(c.is_hidden for c in chain) or s.node.name not in inside:
                continue
            sid = lk.multi_input_sort_id if lk.to_socket.is_multi_input else 0
            muted = any(c.is_muted for c in chain)
            if not lk.to_socket.is_multi_input:
                end = (gid_of(s), lk.to_node.name, tuple(round(v, 1) for v in socket_location(lk.to_socket)), muted)
                if end in ends:
                    twins.setdefault(ends[end], []).append(list(gid_of(lk.to_socket)))
                    continue
                ends[end] = gid_of(lk.to_socket)
            links.append([list(gid_of(s)), list(gid_of(lk.to_socket)), muted, sid])
            pts = []
            for c in chain[1:]:
                x, y = where.get(c.from_node.name, c.from_node.location_absolute)
                pts.append([round(x, 1), round(-y, 1)])
            if pts:
                old_routes[route_key(gid_of(s), gid_of(lk.to_socket), sid)] = pts
    keys = dup.source_keys(nt)
    data = {
        "tree": nt.name,
        "nodes": {},
        "links": sorted(links),
        "removable": sorted(removable),
        "labels": sorted(labels, key=lambda lb: lb["name"]),
        "scale": ui,
        "slot": ortho.slot_gap(ui),
        "routes": old_routes,
        "twins": sorted([list(d), sorted(o)] for d, o in twins.items()),
    }
    linked = {tuple(g) for s, d, _, _ in links for g in (s, d)}
    for n in nodes:
        if n.name in removable:
            continue
        x, y = where.get(n.name, n.location_absolute)
        cx, cy = n.location_absolute  # where it is drawn now
        title = n.node_tree.name if getattr(n, "node_tree", None) else n.bl_label
        parent = n.parent
        while parent is not None and parent.name not in inside:  # a frame outside the part
            parent = parent.parent
        d = {
            "type": n.bl_idname,
            "label": n.label,
            "title": title,
            "parent": parent.name if parent else None,
            "x": x,
            "y": -y,
            "hide": n.hide,
        }
        if n.name in pins:
            d["pin"] = pins[n.name]
        if n.bl_idname == FRAME:
            d.update(w=_size(n.dimensions.x / ui), h=_size(n.dimensions.y / ui), label_size=n.label_size)
            data["nodes"][n.name] = d
            continue
        if n.bl_idname == REROUTE:
            d.update(w=0.0, h=0.0)
        else:
            d.update(w=_size(n.dimensions.x / ui), h=_size(n.dimensions.y / ui))
        po = getattr(n, "paired_output", None)
        d["paired"] = po.name if po is not None else None
        # Blender places sockets whole pixels away from the location rounded to its pixel grid
        bx, by = ortho.to_px(cx, ui), ortho.to_px(cy, ui)
        socks = {}
        for side, coll in (("o", n.outputs), ("i", n.inputs)):
            for k, s in enumerate(coll):
                vis = s.enabled and not s.hide and not n.hide
                if not vis and (n.name, side, k) not in linked:
                    continue
                sx, sy = socket_location(s)
                socks[f"{side}{k}"] = {
                    "off": [round(sx - bx, 4), round(by - sy, 4)],
                    "type": s.type,
                    "vis": vis,
                    "id": s.identifier,
                    "multi": s.is_multi_input,
                }
        d["socks"] = socks
        d["dupkey"] = keys.get(n.name)
        p = comm_pair(n)
        if p:
            a, b = n.inputs[p[0]], n.inputs[p[1]]
            d["comm"] = [p[0], p[1], _same_default(a, b)]
        data["nodes"][n.name] = d
    return data


def _size(v):
    """A node size rounded to drop float noise (the last digits vary with where it is drawn)."""
    return round(v, 3)


def with_modes(low, high):
    """Plain data `low` with both measures of each node (api.read_tree): drawn below y = 0
    (low) and above it (high), as node["modes"] = {"low": (h, {key: [dx, dy]}), "high": ...}."""
    out = dict(low, nodes={})
    for name, d in low["nodes"].items():
        d = dict(d)
        e = high["nodes"].get(name)
        if e is not None and "socks" in d and "socks" in e and d["type"] not in (FRAME, REROUTE) and not d.get("hide"):
            d["modes"] = {
                "low": (d["h"], {k: list(s["off"]) for k, s in d["socks"].items()}),
                "high": (e["h"], {k: list(s["off"]) for k, s in e["socks"].items()}),
            }
        out["nodes"][name] = d
    return out


def at(data, where):
    """Plain data with each node's height and socket offsets for where it is drawn now (Sort
    Selection). where: {node: (x, y)}, Blender's y up (the node's top). Blender rounds each row
    height towards zero from the top down, so the part of a node above y = 0 has the 'high'
    measure and the part below the 'low' one: each stretch between two sockets, top to bottom,
    takes the high height if its middle is above 0 (see api.read_tree)."""
    sc = data.get("scale", 1.0)
    out = dict(data, nodes={})
    for name, d in data["nodes"].items():
        m = d.get("modes")
        if m is None or name not in where:
            out["nodes"][name] = d
            continue
        top = math.floor(where[name][1] * sc + 0.5 + 1e-6)  # pixels, as Blender draws it
        (hl, low), (hh, high) = m["low"], m["high"]
        # the sockets Blender places (the ones in a closed panel keep their low offsets)
        keys = [k for k in low if k in high and abs(high[k][1] - low[k][1]) <= abs(hh - hl) + 2.0 / sc]
        marks = sorted([(high[k][1], low[k][1], k) for k in keys] + [(hh, hl, None)], key=lambda v: (v[0], v[1]))
        got, prev_h, prev_l, prev = {}, 0.0, 0.0, 0.0
        for vh, vl, k in marks:
            step = (vh - prev_h) if top - (prev + (vh - prev_h) / 2) * sc >= 0 else (vl - prev_l)
            prev, prev_h, prev_l = prev + step, vh, vl
            got[k] = prev
        socks = {
            k: dict(s, off=[s["off"][0], round(got[k], 4) if k in got else s["off"][1]]) for k, s in d["socks"].items()
        }
        out["nodes"][name] = dict(d, socks=socks, h=round(got[None], 3))
    return out


def route_key(s, d, sid):
    """Key of a link in data["routes"]: source gid, destination gid and sort id as text."""
    return f"{s[0]}\t{s[1]}{s[2]}\t{d[0]}\t{d[1]}{d[2]}\t{sid}"


class Model:
    """What the layout needs, derived from the plain data."""

    def __init__(self, data):
        """Derive sockets, multi-input slots, main inputs and frame paddings from plain data."""
        self.data = data
        nodes = data["nodes"]
        self.info = nodes
        self.frames = [k for k, d in sorted(nodes.items()) if d["type"] == FRAME]
        self.real = [k for k, d in sorted(nodes.items()) if d["type"] != FRAME]
        self.links = sorted((tuple(s), tuple(d), mu, sid) for s, d, mu, sid in data["links"])
        self.box = {k: (nodes[k]["x"], nodes[k]["y"], nodes[k]["w"], nodes[k]["h"]) for k in self.real}
        self.ins = {k: {} for k in self.real}
        self.outs = {k: {} for k in self.real}
        self.sock_type = {}
        for s, d, _, _ in self.links:
            for g in (s, d):
                self._add(g)
        # commutative pairs that may be swapped, both sockets recorded so a swap can be priced
        self.comm = {}
        for k in self.real:
            c = nodes[k].get("comm")
            if not c:
                continue
            a, b = (k, "i", c[0]), (k, "i", c[1])
            la, lb = self.linked_in(a), self.linked_in(b)
            if ((la and lb) or ((la or lb) and c[2])) and all(f"i{g[2]}" in nodes[k]["socks"] for g in (a, b)):
                self.comm[k] = (a, b)
                self._add(a)
                self._add(b)
        self._multi_slots()
        self.geo = {g: t in FLOW for g, t in self.sock_type.items()}
        self.main = {}
        for k in self.real:
            keys = sorted((g for g in self.ins[k] if self.linked_in(g)), key=lambda g: g[2])
            geo = [g for g in keys if self.geo[g]]
            if keys:
                self.main[k] = (geo or keys)[0]
        self.pads = {}
        for f in self.frames:
            d = nodes[f]
            top = 30.0 + (0.3 * d.get("label_size", 20) if d["label"] else 0.0)
            self.pads[f] = (30.0, top, 30.0, 30.0)

    def _multi_slots(self):
        """Give each link into a multi-input socket (Join Geometry, ...) its own slot key: the
        socket gid plus the slot index (0 = bottom). Blender spreads such links data["slot"]
        apart around the socket centre, highest sort id on top, so they arrive separately. On a
        collapsed node the slots have no offset, but each link still arrives on its own.

        NF035 (params.FAN): a slot's link is laid out to its fan point (_fan), left of the
        socket; self.fan keeps the slot's own offset, where the last stretch ends. A slot level
        with its fan point needs no fan."""
        from . import params as P

        self.slot = {}
        self.fan = {}  # slot key -> (dx, dy) of the slot, for the slots laid out to a fan point
        self.fan_reach = {}  # node -> how far its fans reach out on the left of its box
        gap = self.data.get("slot", SLOT)
        multi = {}
        for s, d, _, sid in self.links:
            node = self.info[d[0]]
            if node["socks"][f"i{d[2]}"].get("multi"):
                multi.setdefault(d, []).append((sid, s))
        for d, ls in sorted(multi.items()):
            if len(ls) < 2:
                continue
            ls.sort()
            n = len(ls)
            x, y = self.ins[d[0]][d]
            hide = self.info[d[0]].get("hide")
            fan = self._fan(d, n, gap) if P.FAN and not hide else None
            for j, (sid, s) in enumerate(ls):
                key = d + (j,)
                off = 0 if hide else (n - 1) * gap / 2 - j * gap
                if fan is not None and abs(fan[1][j] - off) > P.EPS:
                    depth = fan[0]
                    self.ins[d[0]][key] = (x - depth, y + fan[1][j])
                    self.fan[key] = (x, y + off)
                    self.fan_reach[d[0]] = max(self.fan_reach.get(d[0], 0.0), depth - x)
                else:
                    self.ins[d[0]][key] = (x, y + off)
                self.sock_type[key] = self.sock_type[d]
                self.slot[(s, d, sid)] = key

    def _fan(self, d, n, gap):
        """NF035: the fan of multi-input socket d with n links (slots `gap` apart), as (depth,
        [dy of each slot's fan point from the socket, slot 0 = bottom]). Fan points stand
        FAN_GAP apart, centred on the socket, `depth` to its left; to keep FAN_CLEAR from the
        wires into the node's other inputs the fan shifts, then narrows (to FAN_MIN at least).
        depth: at least FAN_DEPTH and FAN_SLOPE times the largest drop to a slot, rounded up to
        a multiple of 10."""
        from . import params as P

        y = self.ins[d[0]][d][1]
        others = [self.ins[d[0]][g][1] - y for g in self.ins[d[0]] if len(g) == 3 and g != d and self.linked_in(g)]
        lo = max([o + P.FAN_CLEAR for o in others if o < 0], default=-math.inf)  # y down: above
        hi = min([o - P.FAN_CLEAR for o in others if o > 0], default=math.inf)
        g = P.FAN_GAP
        if (n - 1) * g > hi - lo:
            g = max(P.FAN_MIN, (hi - lo) / (n - 1))
        span = (n - 1) * g
        top = -span / 2
        if span > hi - lo:
            top = (lo + hi - span) / 2
        elif top < lo:
            top = lo
        elif top + span > hi:
            top = hi - span
        offs = [top + span - j * g for j in range(n)]
        drop = max(abs(f - ((n - 1) * gap / 2 - j * gap)) for j, f in enumerate(offs))
        depth = math.ceil(max(P.FAN_DEPTH, P.FAN_SLOPE * drop) / 10.0 - 1e-9) * 10.0
        return depth, offs

    def slot_at(self, key):
        """Offset (dx, dy) where a link into input key ends at its node: the socket, or its
        multi-input slot (for a slot laid out to a fan point, NF035, the slot itself)."""
        n = key[0]
        return self.fan.get(key) or self.ins[n][key]

    def old_route(self, s, d, sid):
        """Where link (s, d, sid) was drawn before formatting: source socket, reroutes and input
        socket, absolute and y down (the reroutes only if there were any)."""
        a, b = self.box[s[0]], self.box[d[0]]
        k = self.slot_key(s, d, sid)
        p0 = (a[0] + self.outs[s[0]][s][0], a[1] + self.outs[s[0]][s][1])
        p1 = (b[0] + self.ins[d[0]][k][0], b[1] + self.ins[d[0]][k][1])
        mid = [tuple(p) for p in self.data.get("routes", {}).get(route_key(s, d, sid), [])]
        return [p0] + mid + [p1]

    def slot_key(self, s, d, sid):
        """The key a link ends at in the layout: its multi-input slot, else the socket gid."""
        return self.slot.get((s, d, sid), d)

    def _add(self, g):
        """Record the offset and type of a linked socket."""
        n, side, k = g
        s = self.info[n]["socks"][f"{side}{k}"]
        off = tuple(s["off"])
        (self.outs if side == "o" else self.ins)[n][g] = off
        self.sock_type[g] = s["type"]

    def linked_in(self, g):
        """True if input gid g has a link."""
        return any(d == g for _, d, _, _ in self.links)

    def type(self, n):
        """Blender type (bl_idname) of node n."""
        return self.info[n]["type"]

    def parent(self, n):
        """Name of the frame that holds node n, or None."""
        return self.info[n]["parent"]

    def paired(self, n):
        """Name of the zone output paired with zone input n, or None."""
        return self.info[n].get("paired")

    def children_of_frame(self, f):
        """Nodes whose parent is frame f."""
        return [k for k, d in self.info.items() if d["parent"] == f]
