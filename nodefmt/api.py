# SPDX-License-Identifier: GPL-3.0-or-later
"""Format or check node trees. Used by the add-on buttons and by the command line."""
import time
from collections import namedtuple

import bpy

from . import blend, check, dup, lint, model, ortho, rules
from .draw import Editor
from .layout import Formatter


class LogicChanged(Exception):
    """A format would change what the tree computes; the tree was restored."""
    pass


TREE_TYPES = ('GeometryNodeTree', 'ShaderNodeTree', 'CompositorNodeTree')
# data-blocks that embed a node tree (shown in the Shader Editor): label, collection name
OWNERS = (("Material", "materials"), ("World", "worlds"), ("Light", "lights"))


def formattable(nt):
    """True for a Geometry Nodes, Shader or Compositor tree with something to lay out."""
    return nt is not None and nt.bl_idname in TREE_TYPES and len(nt.nodes) > 1


def owner(nt):
    """(label, data-block) of the material, world or light that embeds tree nt, else None."""
    if not getattr(nt, "is_embedded_data", False):
        return None
    for label, coll in OWNERS:
        for idb in getattr(bpy.data, coll):
            if idb.node_tree is not None and idb.node_tree == nt:
                return label, idb
    return None


def tree_name(nt):
    """A name for a tree: a node group's name, or 'Material: Floor' for an embedded tree."""
    o = owner(nt)
    return f"{o[0]}: {o[1].name}" if o else nt.name


def find_tree(name):
    """The tree called `name` (see tree_name), or KeyError."""
    nt = bpy.data.node_groups.get(name)
    if nt is not None:
        return nt
    for label, coll in OWNERS:
        prefix = label + ": "
        if name.startswith(prefix):
            idb = getattr(bpy.data, coll).get(name[len(prefix):])
            if idb is not None and idb.node_tree is not None:
                return idb.node_tree
    raise KeyError(f"no node tree {name!r}")


def _signature(nt):
    """Layout of a tree as plain data: positions of every node and the links between positions."""
    pos = {n.name: (round(n.location_absolute.x, 1), round(n.location_absolute.y, 1))
           for n in nt.nodes if n.bl_idname != 'NodeFrame'}
    real = sorted((v, nt.nodes[k].bl_idname) for k, v in pos.items()
                  if nt.nodes[k].bl_idname != 'NodeReroute' or nt.nodes[k].label)
    rr = sorted(v for k, v in pos.items() if nt.nodes[k].bl_idname == 'NodeReroute' and not nt.nodes[k].label)
    links = sorted((pos[l.from_node.name], pos[l.to_node.name], l.from_socket.identifier, l.to_socket.identifier)
                   for l in nt.links if l.from_node.name in pos and l.to_node.name in pos)
    return real, rr, links


def same_layout(a, b, tol=None):
    """True if two signatures (_signature) are the same layout: the same nodes, reroutes and
    links, every position within a pixel (tol, node units) of the other. At a fractional UI
    scale a reroute may land a fraction of a pixel apart from one format to the next; nobody
    can see that, and it does not make a tree unformatted."""
    tol = 1.0 / ortho.ui_scale() + 0.05 if tol is None else tol

    def flat(v):
        """The numbers and the other values of a signature entry."""
        nums, rest = [], []
        for x in (v if isinstance(v, tuple) else (v,)):
            if isinstance(x, tuple):
                n, r = flat(x)
                nums += n
                rest += r
            elif isinstance(x, float):
                nums.append(x)
            else:
                rest.append(x)
        return nums, rest

    for pa, pb in zip(a, b):
        if len(pa) != len(pb):
            return False
        for x, y in zip(pa, pb):
            (nx, rx), (ny, ry) = flat(x), flat(y)
            if rx != ry or len(nx) != len(ny) or any(abs(u - v) > tol for u, v in zip(nx, ny)):
                return False
    return True


BIG = 100000.0  # read_tree: a height far above y = 0 (every row of a node above it)


def read_tree(nt, editor, part=None, pins=None):
    """model.read with socket offsets that match where each node is drawn.

    At a UI scale other than 1, Blender's node layout rounds each row's float height towards
    zero, row after row from the node's top: the rows of a node above y = 0 are a pixel taller
    than below it, so a tall node's sockets are several pixels apart between the two (and a
    node across y = 0 mixes both). Every node is measured twice, drawn above 0 and below it
    (then put back), and model.at gives its offsets for any height: here, where it is now; the
    format lays the tree out again if the layout moves a node to where its rows differ. The
    measures do not depend on where the nodes are, so each pass sees the same tree. part and
    pins: read only a part of the tree (see model.read); only its nodes are touched."""
    editor.show(nt)
    s = ortho.ui_scale()
    blend.pixel_snap(nt, s, part)
    if abs(s - 1.0) < 1e-6:
        editor.redraw()
        return model.read(nt, part=part, pins=pins)
    where = {n.name: tuple(n.location_absolute) for n in nt.nodes
             if n.bl_idname != 'NodeFrame' and (part is None or n.name in part)}
    try:
        measures = []
        for y in (0.0, BIG):  # below y = 0, then above it
            for name in where:
                nt.nodes[name].location_absolute = (0.0, y)
            editor.redraw()
            measures.append(model.read(nt, where, part=part, pins=pins))
    finally:
        for name, p in where.items():
            nt.nodes[name].location_absolute = p
        editor.redraw()
    data = model.with_modes(*measures)
    return model.at(data, where)


class Step(namedtuple('Step', 'npass phase k n step steps')):
    """Progress of a sort (format_steps): pass `npass`, `phase` (reading, copies, layout,
    routing, writing, straightening, logic check), k of n for the layout (one per container),
    and step `step` of the `steps` of this pass."""

    def text(self):
        """'pass 1 (of at most 6), layout 4/9 (step 6/14)'."""
        what = f"{self.phase} {self.k}/{self.n}" if self.n > 1 else self.phase
        return f"pass {self.npass} (of at most {MAX_PASSES}), {what} (step {self.step}/{self.steps})"


def format_once(nt, mode, editor, duplicates=True, swaps=True, cfg=None):
    """One pass: copies of input nodes, layout, write back, then the drawn wires made exactly
    orthogonal (ortho.straighten). Returns (reroutes, copies, formatter, straighten stats)."""
    return _drain(format_once_steps(nt, mode, editor, duplicates, swaps, cfg))


def format_once_steps(nt, mode, editor, duplicates=True, swaps=True, cfg=None, npass=1):
    """format_once as a generator of Steps; returns what format_once returns."""
    from .layout import containers
    cfg = cfg or rules.Config()
    data = read_tree(nt, editor)
    n = len(containers(model.Model(data))) + 1
    steps = n + 5  # reading, copies, n layouts, routing, writing, straightening (+ logic check)
    step = Step(npass, "reading", 1, 1, 1, steps + 1)
    yield step
    copies = 0
    if duplicates and cfg.on('NF010'):
        plan = dup.plan(data, mode)
        if dup.changes(plan, data):
            copies = dup.realize(nt, editor, plan)
            data = read_tree(nt, editor)
    yield step._replace(phase="copies", step=2)
    f = Formatter(model.Model(data), mode, swaps, rules=cfg.rules)
    for phase, k, m in f.run_steps():
        yield step._replace(phase=phase, k=k, n=m, step=min(2 + k, n + 2) if phase == 'layout' else n + 3)
    # a node the layout moves to where its rows are drawn otherwise (read_tree): lay out again
    # with the offsets of where it goes, until a layout puts every node where its offsets hold;
    # if the layouts go round in a circle (or no layout settles), the one made with the
    # smallest offsets of the circle, so that the next pass makes the same choice
    tried = [(_offsets_key(data), f)]
    for _ in range(RELAYOUTS):
        moved = _drawn_at(data, f)
        if moved is None:
            break
        if any(key == _offsets_key(moved) for key, _ in tried):
            f = min(tried, key=lambda t: t[0])[1]
            break
        data = moved
        f = Formatter(model.Model(data), mode, swaps, rules=cfg.rules)
        for phase, k, m in f.run_steps():
            yield step._replace(phase=phase, k=k, n=m, step=min(2 + k, n + 2) if phase == 'layout' else n + 3)
        tried.append((_offsets_key(data), f))
    else:
        if _drawn_at(data, f) is not None:
            f = min(tried, key=lambda t: t[0])[1]
    made = blend.apply(nt, f)
    yield step._replace(phase="writing", step=n + 4)
    anchor = tuple(nt.nodes[f.anchor].location_absolute)
    editor.show(nt)
    st = ortho.straighten(nt, editor, fan=cfg.on('NF035'))
    if cfg.on('NF034'):
        editor.redraw()
        st["dropped"] = ortho.drop_straight(nt)
    # straighten may have nudged the anchor (the Group Output): move everything back by as much,
    # so the tree stays where it was and a second format finds it in the same place
    a = nt.nodes[f.anchor].location_absolute
    dx, dy = a[0] - anchor[0], a[1] - anchor[1]
    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        for nd in nt.nodes:
            if nd.bl_idname != 'NodeFrame':
                x, y = nd.location_absolute
                nd.location_absolute = (x - dx, y - dy)
        editor.redraw()
    yield step._replace(phase="straightening", step=n + 5)
    return made, copies, f, st


RELAYOUTS = 2  # layouts again with the offsets of where the layout puts the nodes (read_tree)


def _drawn_at(data, f):
    """The data with each node's offsets for where layout f puts it (model.at), or None if no
    node's offsets change: the layout was made with the offsets it will be drawn with."""
    sc = data.get("scale", 1.0)
    where = {k: (ortho.to_px(x, sc), ortho.to_px(-y, sc)) for k, (x, y) in f.pos.items()}
    new = model.at(data, where)
    for k, d in new["nodes"].items():
        old = data["nodes"][k]
        if "modes" in d and (abs(d["h"] - old["h"]) > 0.01 or any(
                abs(s["off"][1] - old["socks"][g]["off"][1]) > 0.01 for g, s in d["socks"].items())):
            return new
    return None


def _offsets_key(data):
    """The heights of the nodes measured both ways (read_tree), as a key that orders the
    offsets a layout was made with."""
    return tuple(sorted((k, d["h"]) for k, d in data["nodes"].items() if "modes" in d))


MAX_PASSES = 6  # full layout passes of one tree; a pass that moves nothing ends the sort


def _drain(gen):
    """Run a generator of Steps to the end; returns its return value."""
    while True:
        try:
            next(gen)
        except StopIteration as e:
            return e.value


def format_tree(nt, mode='relayout', editor=None, duplicates=True, swaps=True, cfg=None):
    """Format one tree in place, with the rules and options of cfg (rules.Config; default: all
    rules, one deterministic pass). On any logic difference the tree is restored and
    LogicChanged raised. Returns a dict of stats."""
    return _drain(format_steps(nt, mode, editor, duplicates, swaps, cfg))


def format_steps(nt, mode='relayout', editor=None, duplicates=True, swaps=True, cfg=None):
    """format_tree as a generator: yields a Step after each step, so a caller can show
    progress (and stop: closing the generator leaves the tree half sorted; restore it from a
    check.Snapshot taken before). Returns the stats of format_tree."""
    cfg = cfg or rules.Config()
    with rules.applied(cfg):
        return (yield from _format_steps(nt, mode, editor, duplicates, swaps, cfg))


def _format_steps(nt, mode, editor, duplicates, swaps, cfg):
    """format_steps with the layout parameters of cfg set."""
    own = editor is None
    editor = editor or Editor()
    t0 = time.perf_counter()
    try:
        editor.show(nt)
        snap = check.Snapshot(nt)
        before = check.fingerprint(nt)
        made = copies = swapped = 0
        # repeated until nothing moves: 'keep' starts from the current layout, and copies of input
        # nodes and swapped inputs change the graph that 'relayout' works on
        for k in range(MAX_PASSES):
            sig = _signature(nt)
            last = None
            try:
                gen = format_once_steps(nt, mode, editor, duplicates, swaps, cfg, k + 1)
                while True:
                    try:
                        last = next(gen)
                    except StopIteration as e:
                        made, c, f, ost = e.value
                        break
                    yield last
                copies += c
                swapped += len(f.swapped)
            except Exception as e:
                snap.restore(nt, editor)
                again = check.diff(before, check.fingerprint(nt))
                raise LogicChanged(f"{tree_name(nt)}: format failed ({e}), reverted "
                                   f"({'restore OK' if not again else 'RESTORE FAILED'})") from e
            d = check.diff(before, check.fingerprint(nt))
            if d:
                snap.restore(nt, editor)
                again = check.diff(before, check.fingerprint(nt))
                raise LogicChanged(f"{tree_name(nt)}: format changed the logic, reverted "
                                   f"({'restore OK' if not again else 'RESTORE FAILED'}): {d[:3]}")
            yield last._replace(phase="logic check", k=1, n=1, step=last.steps)
            editor.show(nt)
            if k and same_layout(_signature(nt), sig):
                break
        editor.redraw()
        return {"tree": tree_name(nt), "seconds": round(time.perf_counter() - t0, 3),
                "reroutes": made, "copies": copies, "swaps": swapped,
                "loose_frames": sorted(f.loose_frames), "passes": k + 1,
                # the last pass's straighten (ortho.py) and the UI scale the layout was made for
                "ortho": ost, "ui_scale": round(ortho.ui_scale(), 4),
                # layout cost of the last pass (sum over containers) and how each container was placed
                "cost": round(sum(r.cost for _, r in f.res.values()), 3),
                "tidy": dict(getattr(f, "tidy", {})),
                "placers": sorted(str(r.placer) for _, r in f.res.values())}
    finally:
        if own:
            editor.close()


def is_formatted(nt, mode='relayout', editor=None, cfg=None):
    """True if every drawn wire segment is horizontal or vertical (at the UI scale of the session)
    and formatting would not move anything. The tree is left unchanged."""
    return unformatted(nt, mode, editor, cfg) is None


def unformatted(nt, mode='relayout', editor=None, cfg=None):
    """None if the tree is formatted (see is_formatted), else the names of the nodes a format
    would move (or, if none moves, of the nodes whose wires would change). The tree is left
    unchanged."""
    own = editor is None
    editor = editor or Editor()
    try:
        editor.show(nt)
        bad = ortho.faults(nt, fan=(cfg or rules.Config()).on('NF035'))
        if bad:
            return sorted({n for l, _, _ in bad for n in (l.from_node.name, l.to_node.name)})
        snap = check.Snapshot(nt)
        sig = _signature(nt)
        where = {n.name: tuple(n.location_absolute) for n in nt.nodes
                 if n.bl_idname not in ('NodeFrame', 'NodeReroute')}
        try:
            format_tree(nt, mode, editor, cfg=cfg)
            editor.show(nt)
            new = _signature(nt)
            tol = 1.0 / ortho.ui_scale() + 0.05
            moved = sorted(k for k, p in where.items() if nt.nodes.get(k) is None
                           or max(abs(a - b) for a, b in zip(nt.nodes[k].location_absolute, p)) > tol)
            if not moved:
                ends = {}
                for l in nt.links:
                    if l.from_node.bl_idname == 'NodeReroute' or l.to_node.bl_idname == 'NodeReroute':
                        ends.setdefault(l.from_node.name, 0)
                        ends.setdefault(l.to_node.name, 0)
                moved = sorted(k for k in ends if k in where)
        finally:
            snap.restore(nt, editor)
            editor.redraw()
        return None if same_layout(new, sig) else moved
    finally:
        if own:
            editor.close()


def all_trees():
    """The local (not linked) trees of the file that can be formatted: node groups of every
    supported type (Geometry Nodes, shader and compositor groups, the scene compositor), then
    the trees of materials, worlds and lights."""
    trees = [nt for nt in bpy.data.node_groups if formattable(nt) and not nt.library]
    for _, coll in OWNERS:
        trees += [idb.node_tree for idb in getattr(bpy.data, coll)
                  if not idb.library and formattable(idb.node_tree)]
    return trees


def check_tree(nt, mode='relayout', editor=None, cfg=None, formatted=True):
    """The rules tree nt breaks, as lint.Violations (code, name, message, x, y with y up, the
    nodes involved), for the enabled rules of cfg. formatted=True also tries a format (on a
    snapshot, undone) and adds NF900 not-formatted if it would move anything (the nodes it would
    move). The tree is left unchanged."""
    from . import metrics
    cfg = cfg or rules.Config()
    own = editor is None
    editor = editor or Editor()
    try:
        editor.show(nt)
        data = read_tree(nt, editor)
        editor.show(nt)
        d, labels, groups = metrics.drawing(nt, data)
        out = lint.lint(d, cfg.rules, labels, groups)
        if cfg.on('NF010') and mode == 'relayout':
            with rules.applied(cfg):
                plan = dup.plan(data, mode)
            if dup.changes(plan, data):
                names = sorted({n for c in plan["classes"] for n in [c["rep"]] + list(c["remove"])
                                + [g["node"] for g in c["groups"] if g["node"]]})
                out.append(lint.Violation('NF010', rules.NAMES['NF010'],
                                          "input nodes would get copies next to their distant consumers", 0.0, 0.0,
                                          tuple(names)))
        if cfg.on('NF011'):
            out += _comm_crossings(d, model.Model(data))
        if formatted:
            moved = unformatted(nt, mode, editor, cfg)
            if moved is not None:
                out.append(lint.Violation('NF900', 'not-formatted', "formatting would change the layout",
                                          0.0, 0.0, tuple(moved)))
        return out
    finally:
        if own:
            editor.close()


def _comm_crossings(d, m):
    """NF011: the wires into the two inputs of a commutative node cross each other."""
    from . import wires
    out = []
    for node, (a, b) in sorted(m.comm.items()):
        ta = [tag for tag, t in d.trees.items() if any(k[:3] == a for k in t.dst.values())]
        tb = [tag for tag, t in d.trees.items() if any(k[:3] == b for k in t.dst.values())]
        hit = None
        for x in ta:
            for y in tb:
                if x == y:
                    continue
                for s in d.tree_segments(x):
                    for o in d.tree_segments(y):
                        p = wires.crossing(s, o) if wires.horiz(s) and wires.vert(o) else                             wires.crossing(o, s) if wires.vert(s) and wires.horiz(o) else None
                        if p is not None:
                            hit = p
        if hit is not None:
            out.append(lint.Violation('NF011', rules.NAMES['NF011'],
                                      f"the wires into the inputs of {node!r} cross; swapping them would not",
                                      round(hit[0], 1), round(-hit[1], 1), (node,)))
    return out
