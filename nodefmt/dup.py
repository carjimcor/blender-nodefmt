# SPDX-License-Identifier: GPL-3.0-or-later
"""Copies of input-like nodes, so that each group of consumers gets a source next to it.

An input-like node has nothing linked into it (Group Input, Named Attribute, Index, Position,
constants, ...). Nodes that compute the same thing (same type, properties and socket values)
form a class, whose members the logic check treats as one source (check.py). Never copied:
String nodes, labelled nodes, reroutes, frames, zone and output nodes, and nodes that load data.

plan() (pure) merges each class into one member, lays the merged tree out, groups the
consumers by where they land and gives each distant group its own member: existing members are
reused, new ones are copies, unlinked ones are removed. The plan does not depend on the members
that exist now, so formatting twice gives the same result. realize() carries it out in Blender.
"""
import copy as _copy
import hashlib

INPUTS = {'NodeGroupInput', 'ShaderNodeValue', 'FunctionNodeInputInt', 'FunctionNodeInputBool',
          'FunctionNodeInputVector', 'FunctionNodeInputColor', 'FunctionNodeInputRotation',
          'FunctionNodeInputSpecialCharacters', 'GeometryNodeCollectionInfo', 'GeometryNodeObjectInfo',
          'GeometryNodeSelfObject', 'GeometryNodeIsViewport',
          # shader nodes that only read the shading point or hold a constant (no inputs)
          'ShaderNodeRGB', 'ShaderNodeTexCoord', 'ShaderNodeAttribute', 'ShaderNodeNewGeometry',
          'ShaderNodeObjectInfo', 'ShaderNodeCameraData', 'ShaderNodeLightPath', 'ShaderNodeUVMap',
          'ShaderNodeVertexColor', 'ShaderNodeHairInfo', 'ShaderNodePointInfo', 'ShaderNodeParticleInfo',
          'ShaderNodeVolumeInfo',
          # compositor constants
          'CompositorNodeRGB', 'CompositorNodeValue', 'CompositorNodeNormal'}
# never copied: text, and nodes that load data or render (images, textures, render layers, masks,
# movie clips, scene and sequencer inputs), even with nothing linked in
NEVER = {'FunctionNodeInputString', 'ShaderNodeTexImage', 'ShaderNodeTexEnvironment', 'CompositorNodeImage',
         'CompositorNodeRLayers', 'CompositorNodeMask', 'CompositorNodeMovieClip', 'CompositorNodeTexture',
         'CompositorNodeTrackPos', 'CompositorNodeImageInfo', 'CompositorNodeSequencerStripInfo'}
SPLIT = 160.0   # consumers further apart than this (vertically, in one column) are separate groups
NEAR = 360.0    # a group this close (route length) to the merged source shares it


# ---------------------------------------------------------------- Blender side
def duplicable(n):
    """True for an input-like node with nothing linked in and no label: one of INPUTS or a
    field input 'GeometryNodeInput*' (Index, Position, ...), never one of NEVER."""
    t = n.bl_idname
    if t in NEVER or n.label:
        return False
    if t not in INPUTS and not t.startswith('GeometryNodeInput'):
        return False
    if any(s.is_linked for s in n.inputs):
        return False
    return len(n.outputs) > 0


def source_keys(nt):
    """Class key of every duplicable node: what it computes, not its name or place."""
    from .check import _props, _val
    keys = {}
    for n in nt.nodes:
        if n.bl_idname != 'NodeReroute' and duplicable(n):
            ins = [(s.identifier, s.name, s.enabled, _val(getattr(s, "default_value", None))) for s in n.inputs]
            outs = [s.identifier for s in n.outputs]
            props = {k: v for k, v in _props(n).items() if k not in ("name", "is_active_output", "hide", "label")}
            sig = repr((n.bl_idname, sorted(props.items()), ins, outs))
            keys[n.name] = "src:" + hashlib.sha1(sig.encode()).hexdigest()[:16]
    return keys


def realize(nt, editor, plan):
    """Carry out a plan in Blender. Returns the number of copies made."""
    made = 0
    for cls in plan["classes"]:
        groups = cls["groups"]
        rep = nt.nodes[cls["rep"]]
        for g in groups:
            node = nt.nodes[g["node"]] if g["node"] else None
            if node is None:
                node = _copy_node(nt, editor, rep)
                made += 1
            if g["move"]:
                node.parent = nt.nodes[g["parent"]] if g["parent"] else None
                c = nt.nodes[g["dsts"][0][1][0]]
                node.location_absolute = (c.location_absolute.x - node.width - 60, c.location_absolute.y)
            used = set()
            for k, d in g["dsts"]:
                to = nt.nodes[d[0]].inputs[d[2]]
                frm = node.outputs[k]
                old = [l for l in to.links if not l.is_hidden]
                if old and _source_socket(old[0]) == frm.as_pointer():
                    used.add(k)  # fed by this member already (directly or through reroutes)
                    continue
                mu = old[0].is_muted if old else False
                was = old[0].from_node if old else None
                l = nt.links.new(frm, to)
                l.is_muted = mu
                used.add(k)
                _prune(nt, was)
            if node.bl_idname == 'NodeGroupInput':
                for k, o in enumerate(node.outputs):  # a Group Input shows only what it feeds
                    if o.hide != (k not in used):
                        o.hide = k not in used
        for name in cls["remove"]:
            n = nt.nodes.get(name)
            if n is not None and not any(o.is_linked for o in n.outputs):
                nt.nodes.remove(n)
    editor.show(nt)
    return made


def _source_socket(link):
    """as_pointer() of the real output socket feeding a link, through reroutes (None if none)."""
    for _ in range(1000):
        if link.from_node.bl_idname != 'NodeReroute':
            return link.from_socket.as_pointer()
        ins = link.from_node.inputs[0].links
        if not ins:
            return None
        link = ins[0]
    return None


def _prune(nt, node):
    """Remove reroute `node` and the reroutes above it while they lead nowhere: what is left of
    a wire whose destination now gets its link from another member."""
    while node is not None and node.bl_idname == 'NodeReroute' and not node.outputs[0].is_linked:
        ins = node.inputs[0].links
        up = ins[0].from_node if ins else None
        nt.nodes.remove(node)
        node = up


def _copy_node(nt, editor, node):
    """A full copy of a node (properties, hidden values), made with Blender's own duplicate."""
    import bpy
    for n in nt.nodes:
        n.select = False
    node.select = True
    nt.nodes.active = node
    region = next(r for r in editor.area.regions if r.type == 'WINDOW')
    before = {n.as_pointer() for n in nt.nodes}
    with bpy.context.temp_override(window=editor.win, area=editor.area, region=region):
        bpy.ops.node.duplicate(keep_inputs=False)
    new = [n for n in nt.nodes if n.as_pointer() not in before]
    if len(new) != 1:
        raise RuntimeError(f"could not duplicate {node.name}")
    new[0].select = False
    node.select = False
    return new[0]


# ---------------------------------------------------------------- plan (pure)
def _classes(data):
    """Classes of duplicable nodes that have links: {class key: [member names]}. A class that feeds
    a multi-input socket is left alone (the order of its links matters)."""
    cls = {}
    for name, d in data["nodes"].items():
        if d.get("dupkey"):
            cls.setdefault(d["dupkey"], []).append(name)
    linked_from = {s[0] for s, _, _, _ in data["links"]}
    multi = {s[0] for s, d, _, _ in data["links"]
             if data["nodes"][d[0]].get("socks", {}).get(f"i{d[2]}", {}).get("multi")}
    out = {}
    for k, names in cls.items():
        live = sorted(n for n in names if n in linked_from)
        if live and not any(n in multi for n in names):  # multi-input links keep their order
            out[k] = live
    return out


def merged(data):
    """The tree with every class merged into its first member by name. Returns (data, {member:
    kept member}, {(source, input): original input} for links of commutative pairs, which are
    put in a fixed order)."""
    data = _copy.deepcopy(data)
    rep_of = {}
    for names in _classes(data).values():
        for n in names:
            rep_of[n] = names[0]
    data["links"] = [[[rep_of.get(s[0], s[0]), s[1], s[2]], d, mu, sid] for s, d, mu, sid in data["links"]]
    for n, r in rep_of.items():
        if n != r:
            del data["nodes"][n]
    # commutative pairs in a fixed order (by source), so the plan does not depend on swaps
    actual = {}
    by_dst = {}
    for l in data["links"]:
        by_dst.setdefault(tuple(l[1]), []).append(l)
    for name, v in data["nodes"].items():
        c = v.get("comm")
        if not c:
            continue
        a, b = (name, 'i', c[0]), (name, 'i', c[1])
        ls = sorted(by_dst.get(a, []) + by_dst.get(b, []), key=lambda l: repr(l[0]))
        for l, slot in zip(ls, (a, b)):
            actual[(tuple(l[0]), slot)] = tuple(l[1])
            l[1] = list(slot)
    return data, rep_of, actual


def plan(data, mode='relayout'):
    """The copy plan of a tree (see the module docstring): for each class, the groups of consumer
    sockets, which member feeds each group (existing or new) and which members are removed."""
    from .layout import Formatter
    from .model import Model
    classes = _classes(data)
    res = {"classes": []}
    if not classes:
        return res
    mdata, _rep_of, actual = merged(data)
    for k, names in classes.items():
        rep = names[0]
        socks = mdata["nodes"][rep]["socks"]
        for n in names[1:]:
            for key, s in data["nodes"][n]["socks"].items():
                socks.setdefault(key, s)
        if mdata["nodes"][rep]["type"] == 'NodeGroupInput':  # the same shape however it shows now
            _show_only(mdata["nodes"][rep], sorted({s[2] for s, _, _, _ in mdata["links"] if s[0] == rep}))
    m = Model(mdata)
    from . import params as P
    # the graph only, not the old positions (no STABLE), and one seed: more give another plan,
    # often a worse tree
    stable, seeds, P.STABLE, P.SEEDS = P.STABLE, P.SEEDS, None, 1
    try:
        f = Formatter(m, mode, swaps=False).run(route=False)  # node positions are all it needs
    finally:
        P.STABLE, P.SEEDS = stable, seeds
    current = {}  # dst gid -> member feeding it now
    for s, d, _, _ in data["links"]:
        current[tuple(d)] = s[0]
    for k, names in sorted(classes.items()):
        rep = names[0]
        sx, sy = f.pos[rep]
        dsts = []
        for s, d, _, _ in m.links:
            if s[0] != rep:
                continue
            x, y = f.pos[d[0]]
            dy = m.ins[d[0]][d][1]
            c = mdata["nodes"][d[0]].get("comm")
            socks = mdata["nodes"][d[0]]["socks"]
            if c and d[2] in c[:2] and all(f"i{j}" in socks for j in c[:2]):
                dy = min(socks[f"i{j}"]["off"][1] for j in c[:2])  # the plan must not depend on swaps
            h = f.home[d[0]]
            dsts.append({"k": s[2], "d": actual.get((s, d), d), "x": x, "y": y + dy, "home": h,
                         "rank": f.node_items[d[0]].rank})
        groups = _group(dsts)
        # the group nearest to the merged source keeps it; groups close to it share it
        ox, oy = sx + m.box[rep][2], sy
        dist = lambda g, ox=ox, oy=oy: min(abs(t["x"] - ox) + abs(t["y"] - oy) for t in g)
        groups.sort(key=dist)
        keep, own = list(groups[0]), []
        col = lambda g: (id(g[0]["home"]), g[0]["rank"])
        for g in groups[1:]:
            if dist(g) <= NEAR and col(g) != col(groups[0]):  # split within a column on purpose
                keep += g
            else:
                own.append(g)
        out = []
        for g in [keep] + own:
            homes = {t["home"] for t in g}
            parent = None
            if len(homes) == 1:
                h = next(iter(homes))
                if h.kind == 'frame':
                    parent = h.key
            out.append({"dsts": sorted((t["k"], t["d"]) for t in g), "parent": parent})
        # existing members keep the groups they already feed most; other groups reuse a free
        # member (moved to the group's frame), else get a new copy
        free = list(names)
        for g in sorted(out, key=lambda g: (-len(g["dsts"]), g["dsts"])):
            score = {n: sum(1 for _, d in g["dsts"] if current.get(d) == n) for n in free}
            best = max(free, key=lambda n: (score[n], [-ord(c) for c in n])) if free else None
            g["node"] = best if best is not None and score[best] > 0 else None
            g["move"] = g["node"] is None
            if g["node"]:
                free.remove(best)
        for g in sorted(out, key=lambda g: (-len(g["dsts"]), g["dsts"])):
            if g["node"] is None and free:
                g["node"] = free.pop(0)
        res["classes"].append({"key": k, "rep": rep, "groups": out, "remove": free,
                               "dsts": [list(map(list, g["dsts"])) for g in out]})
    return res


def _group(dsts):
    """Consumer sockets in one container and column, split where they are far apart vertically."""
    by = {}
    for t in dsts:
        by.setdefault((id(t["home"]), t["rank"]), []).append(t)
    groups = []
    for key in sorted(by, key=lambda k: min((t["x"], t["y"]) for t in by[k])):
        ts = sorted(by[key], key=lambda t: (t["y"], t["k"], t["d"][0]))
        cur = [ts[0]]
        for t in ts[1:]:
            # far apart, or fed from an output above the previous one (one copy would cross itself)
            if t["y"] - cur[-1]["y"] > SPLIT or t["k"] < cur[-1]["k"]:
                groups.append(cur)
                cur = []
            cur.append(t)
        groups.append(cur)
    return groups


def changes(plan, data):
    """True if carrying out the plan would change the tree."""
    cur = {tuple(d): s[0] for s, d, _, _ in data["links"]}
    for cls in plan["classes"]:
        if cls["remove"]:
            return True
        for g in cls["groups"]:
            if g["node"] is None or any(cur.get(tuple(d)) != g["node"] for _, d in g["dsts"]):
                return True
            n = data["nodes"][g["node"]]
            if n["type"] == 'NodeGroupInput':
                shown = {int(k[1:]) for k, v in n["socks"].items() if k[0] == 'o' and v["vis"]}
                if shown != {k for k, _ in g["dsts"]}:
                    return True
    return False


def apply_model(data, plan):
    """The plan carried out on plain data (offline tests). Copies get the geometry Blender would
    give them: a Group Input copy shows only the outputs it feeds."""
    data = _copy.deepcopy(data)
    links = [[s, d, mu, sid] for s, d, mu, sid in data["links"]]
    by_dst = {tuple(l[1]): l for l in links}  # class links never go to multi-input sockets
    made = 0
    for cls in plan["classes"]:
        rep = data["nodes"][cls["rep"]]
        for g in cls["groups"]:
            name = g["node"]
            if name is None:
                made += 1
                name = f"{cls['rep']}~{made}"
                c = _copy.deepcopy(rep)
                used = sorted({k for k, _ in g["dsts"]})
                if c["type"] == 'NodeGroupInput':
                    _show_only(c, used)
                data["nodes"][name] = c
            node = data["nodes"][name]
            if node["type"] == 'NodeGroupInput' and g["node"] is not None:
                _show_only(node, sorted({k for k, _ in g["dsts"]}))
            if g["move"]:
                node["parent"] = g["parent"]
                cons = data["nodes"][g["dsts"][0][1][0]]
                node["x"], node["y"] = cons["x"] - node["w"] - 60, cons["y"]
            for k, d in g["dsts"]:
                key = f"o{k}"
                if key not in node["socks"]:
                    alt = [v["socks"][key] for v in data["nodes"].values()
                           if v.get("dupkey") == cls["key"] and key in v.get("socks", {})]
                    node["socks"][key] = _copy.deepcopy(alt[0])
                by_dst[tuple(d)][0] = [name, 'o', k]
        for n in cls["remove"]:
            data["nodes"].pop(n, None)
    data["links"] = sorted(links)
    return data, made


def _show_only(c, used):
    """Make a Group Input record show only the outputs `used`, with Blender's row spacing."""
    outs = sorted((int(k[1:]), s) for k, s in c["socks"].items() if k[0] == 'o' and s["vis"])
    if len(outs) < 1:
        return
    ys = sorted(s["off"][1] for _, s in outs)
    step = (ys[-1] - ys[0]) / (len(ys) - 1) if len(ys) > 1 else 22.0
    if not 18.0 <= step <= 26.0:
        step = 22.0  # sockets read from several members: Blender's row height
    bottom = c["h"] - ys[-1] if c["h"] - ys[-1] > 0 else 17.0
    socks = {k: s for k, s in c["socks"].items() if k[0] != 'o'}
    for n, k in enumerate(used):
        s = _copy.deepcopy(c["socks"].get(f"o{k}") or outs[0][1])
        s["off"] = [s["off"][0], ys[0] + n * step]
        socks[f"o{k}"] = s
    c["socks"] = socks
    c["h"] = ys[0] + (len(used) - 1) * step + bottom
