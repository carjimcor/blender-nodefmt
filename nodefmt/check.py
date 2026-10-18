# SPDX-License-Identifier: GPL-3.0-or-later
"""Logic fingerprint of a node tree, and a snapshot to undo a format.

The fingerprint has no layout data: node properties and socket values (hidden ones too),
parents, zone pairs, the group interface, and links resolved through reroutes (with the order
of multi-input sockets). Trees with equal fingerprints compute the same thing. String values
are hashed so no text from the file is kept.
"""

import hashlib

SKIP = {
    "location",
    "location_absolute",
    "width",
    "height",
    "dimensions",
    "select",
    "rna_type",
    "internal_links",
    "inputs",
    "outputs",
    "parent",
    "warning_propagation",
    "is_active_output",
    "show_options",
    "show_preview",
    "show_texture",
    "bl_static_type",
    "color_tag",
    "debug_zone_body_lazy_function_graph",
    "debug_zone_lazy_function_graph",
}


def _val(v):
    """A plain, comparable value of a property (strings hashed, ID blocks by name)."""
    if isinstance(v, str):
        return "str:" + hashlib.sha1(v.encode()).hexdigest()[:12]
    if isinstance(v, (int, float, bool)) or v is None:
        return v
    if hasattr(v, "bl_rna") and isinstance(getattr(v, "name", None), str):
        return "id:" + v.name
    try:
        return [_val(x) for x in v]
    except TypeError:
        return repr(v)


def _props(obj):
    """Plain values of the RNA properties of a node, except layout ones (location, size, ...)."""
    d = {}
    for p in obj.bl_rna.properties:
        k = p.identifier
        if k in SKIP or p.type == "COLLECTION":
            continue
        try:
            d[k] = _val(getattr(obj, k))
        except Exception:  # noqa: BLE001 - any property bpy cannot read is recorded as such
            d[k] = "err"
    return d


def _sock(s):
    """Identity, visibility and stored value of a socket."""
    d = {"id": s.identifier, "name": s.name, "hide": s.hide, "enabled": s.enabled}
    if hasattr(s, "default_value"):
        d["default"] = _val(s.default_value)
    return d


def _resolve_from(link, muted=False):
    """Real output socket(s) feeding a link, through reroutes; a link counts as muted if any link
    on the way is muted."""
    muted = muted or link.is_muted
    n = link.from_node
    if n.bl_idname != "NodeReroute":
        return [(n.name, link.from_socket.identifier, muted)]
    res = []
    for lk in n.inputs[0].links:
        res += _resolve_from(lk, muted)
    return res or [("<dangling reroute>", "", muted)]


def _state(s, name):
    """What an input of a commutative pair receives: its links (resolved) or its own value."""
    links = [lk for lk in s.links if not lk.is_hidden]
    if links:
        return ("link", sorted((name(a), b, mu) for lk in links for a, b, mu in _resolve_from(lk)))
    return ("value", _val(getattr(s, "default_value", None)))


def fingerprint(nt):
    """The logic fingerprint of a tree (see the module docstring); plain data."""
    from .dup import source_keys
    from .model import comm_pair

    src = source_keys(nt)

    def name(n):
        return src.get(n, n)

    nodes = {}
    comm = {}
    for n in nt.nodes:
        if n.bl_idname == "NodeReroute" or n.name in src:
            continue
        nodes[n.name] = {
            "type": n.bl_idname,
            "parent": n.parent.name if n.parent else None,
            "props": _props(n),
            "inputs": [_sock(s) for s in n.inputs],
            "outputs": [_sock(s) for s in n.outputs],
            "paired": getattr(getattr(n, "paired_output", None), "name", None),
        }
        p = comm_pair(n)
        if p:
            # a commutative pair (Add, Multiply, AND, Equal, ...): which input gets which link
            # does not matter; stored values stay in "inputs" (a swap moves links only)
            a, b = n.inputs[p[0]], n.inputs[p[1]]
            comm[(n.name, a.identifier)] = comm[(n.name, b.identifier)] = n.name
            nodes[n.name]["pair"] = sorted([repr(_state(a, name)), repr(_state(b, name))])
    resolved = set()
    for lk in nt.links:
        if lk.to_node.bl_idname == "NodeReroute":
            continue
        if (lk.to_node.name, lk.to_socket.identifier) in comm:
            continue
        for fn, fs, mu in _resolve_from(lk):
            resolved.add((name(fn), fs, name(lk.to_node.name), lk.to_socket.identifier, mu))
    multi = {}
    for n in nt.nodes:
        for s in n.inputs:
            if s.is_multi_input and s.links:
                ls = sorted(s.links, key=lambda lk: lk.multi_input_sort_id)
                multi[f"{name(n.name)}:{s.identifier}"] = [
                    [(name(a), b, mu) for a, b, mu in _resolve_from(lk)] for lk in ls
                ]
    iface = [
        (i.item_type, getattr(i, "in_out", None), i.name, _val(getattr(i, "default_value", None)))
        for i in nt.interface.items_tree
    ]
    return {
        "nodes": nodes,
        "links": sorted(resolved),
        "multi": multi,
        "interface": iface,
        "sources": sorted(set(src.values())),
    }


def diff(a, b):
    """Human-readable list of logic differences between two fingerprints (empty if equal)."""
    out = []
    for k in ("links", "multi", "interface", "sources"):
        if a[k] != b[k]:
            if isinstance(a[k], list):
                sa, sb = set(map(repr, a[k])), set(map(repr, b[k]))
                out.append(f"{k}: removed {sorted(sa - sb)[:3]} added {sorted(sb - sa)[:3]}")
            else:
                out.append(f"{k} differ")
    na, nb = a["nodes"], b["nodes"]
    if set(na) != set(nb):
        out.append(f"nodes: removed {sorted(set(na) - set(nb))} added {sorted(set(nb) - set(na))}")
    for n in set(na) & set(nb):
        for k in na[n]:
            if na[n][k] != nb[n].get(k):
                out.append(f"node {n!r}: {k}")
    return out


class Snapshot:
    """Everything a format can change: node locations and parents, reroutes, links, and copies
    of input nodes (added or removed). Nodes are kept by name, never by Python reference."""

    def __init__(self, nt):
        """Record the layout state of tree `nt`."""
        from .dup import source_keys

        keys = source_keys(nt)
        self.nodes = {}
        for n in nt.nodes:
            if n.bl_idname == "NodeReroute":
                continue
            self.nodes[n.name] = {
                "loc": tuple(n.location),
                "parent": n.parent.name if n.parent else None,
                "size": (n.width, n.height) if n.bl_idname == "NodeFrame" else None,
                "key": keys.get(n.name),
                "hide": [o.hide for o in n.outputs],
            }
        self.reroutes = [
            (n.name, n.label, n.parent.name if n.parent else None, tuple(n.location))
            for n in nt.nodes
            if n.bl_idname == "NodeReroute"
        ]
        links = []
        for lk in nt.links:
            sid = lk.multi_input_sort_id if lk.to_socket.is_multi_input else 0
            links.append(
                (
                    lk.from_node.name,
                    list(lk.from_node.outputs).index(lk.from_socket),
                    lk.to_node.name,
                    list(lk.to_node.inputs).index(lk.to_socket),
                    lk.is_muted,
                    sid,
                )
            )
        self.links = sorted(links, key=lambda x: x[5])

    def restore(self, nt, editor=None):
        """Put everything back. Inputs are relinked before anything is removed, so no socket is
        left unlinked on the way (the Viewer drops unlinked items)."""
        from .blend import set_locations
        from .dup import _copy_node, source_keys

        current = [n for n in nt.nodes if n.bl_idname == "NodeReroute"]
        for k, n in enumerate(current):  # free their names for the reroutes put back
            n.name = f"nodefmt_tmp_{k}"
        # input nodes removed as unused copies: copy a node of the same class back
        missing = [k for k in self.nodes if nt.nodes.get(k) is None]
        if missing:
            keys = source_keys(nt)
            for name in missing:
                want = self.nodes[name]["key"]
                src = next((nt.nodes[k] for k, v in sorted(keys.items()) if v == want), None)
                if src is None or editor is None:
                    raise RuntimeError(f"restore {nt.name}: cannot bring back {name}")
                c = _copy_node(nt, editor, src)
                c.name = name
                for o, h in zip(c.outputs, self.nodes[name]["hide"]):
                    o.hide = h
        for name, info in self.nodes.items():
            n = nt.nodes[name]
            p = info["parent"]
            if (n.parent.name if n.parent else None) != p:
                n.parent = nt.nodes[p] if p else None
        locs = {}  # set in one call (blend.set_locations)
        for name, label, parent, loc in self.reroutes:
            r = nt.nodes.new("NodeReroute")
            r.name = name
            r.label = label
            if parent:
                r.parent = nt.nodes[parent]
            locs[r.name] = loc
        for name, info in self.nodes.items():
            n = nt.nodes[name]
            locs[name] = info["loc"]
            if info["key"]:
                for o, h in zip(n.outputs, info["hide"]):
                    if o.hide != h:
                        o.hide = h
            if info["size"]:
                n.width, n.height = info["size"]
        set_locations(nt, locs, "location")
        multi = {}
        for fn, fi, tn, ti, muted, sid in self.links:
            # look sockets up again for every link: Python references go stale as links change
            to = nt.nodes[tn].inputs[ti]
            if to.is_multi_input:
                multi.setdefault((tn, ti), []).append((fn, fi, muted))
                continue
            frm = nt.nodes[fn].outputs[fi]
            if to.is_linked and to.links[0].from_socket.as_pointer() == frm.as_pointer():
                to.links[0].is_muted = muted
                continue
            lk = nt.links.new(frm, to)
            if lk is None:
                raise RuntimeError(f"restore {nt.name}: could not link {fn}[{fi}] -> {tn}[{ti}]")
            lk.is_muted = muted
        for (tn, ti), lst in multi.items():
            for lk in list(nt.nodes[tn].inputs[ti].links):
                nt.links.remove(lk)
            for fn, fi, muted in lst:
                lk = nt.links.new(nt.nodes[fn].outputs[fi], nt.nodes[tn].inputs[ti])
                if lk is None:
                    raise RuntimeError(f"restore {nt.name}: could not link {fn}[{fi}] -> {tn}[{ti}]")
                lk.is_muted = muted
        keep_names = set(self.nodes) | {r[0] for r in self.reroutes}
        for n in list(nt.nodes):  # leftover reroutes and copies the format added
            if n.name not in keep_names:
                nt.nodes.remove(n)
        keep = {(fn, fi, tn, ti) for fn, fi, tn, ti, _, _ in self.links}
        for lk in list(nt.links):
            key = (
                lk.from_node.name,
                list(lk.from_node.outputs).index(lk.from_socket),
                lk.to_node.name,
                list(lk.to_node.inputs).index(lk.to_socket),
            )
            if key not in keep:
                nt.links.remove(lk)
