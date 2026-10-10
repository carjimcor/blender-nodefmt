# SPDX-License-Identifier: GPL-3.0-or-later
"""Format or check node trees. Used by the add-on buttons and by the command line."""
import time

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


def read_tree(nt, editor):
    """model.read with socket offsets that do not depend on where the nodes are. At a UI scale
    other than 1, Blender's node layout rounds float row heights, so a node's height and socket
    offsets change by a pixel or more with its location; the nodes are drawn at one place for
    the measure (then put back), so every pass of a format sees the same tree."""
    editor.show(nt)
    s = ortho.ui_scale()
    blend.pixel_snap(nt, s)
    if abs(s - 1.0) < 1e-6:
        editor.redraw()
        return model.read(nt)
    where = {n.name: tuple(n.location_absolute) for n in nt.nodes if n.bl_idname != 'NodeFrame'}
    try:
        for name in where:
            nt.nodes[name].location_absolute = (0.0, 0.0)
        editor.redraw()
        return model.read(nt, where)
    finally:
        for name, p in where.items():
            nt.nodes[name].location_absolute = p
        editor.redraw()


def format_once(nt, mode, editor, duplicates=True, swaps=True, cfg=None):
    """One pass: copies of input nodes, layout, write back, then the drawn wires made exactly
    orthogonal (ortho.straighten). Returns (reroutes, copies, formatter, straighten stats)."""
    cfg = cfg or rules.Config()
    data = read_tree(nt, editor)
    copies = 0
    if duplicates and cfg.on('NF010'):
        plan = dup.plan(data, mode)
        if dup.changes(plan, data):
            copies = dup.realize(nt, editor, plan)
            data = read_tree(nt, editor)
    f = Formatter(model.Model(data), mode, swaps, rules=cfg.rules).run()
    made = blend.apply(nt, f)
    anchor = tuple(nt.nodes[f.anchor].location_absolute)
    editor.show(nt)
    st = ortho.straighten(nt, editor)
    if cfg.on('NF034'):
        editor.redraw()
        st["dropped"] = ortho.drop_straight(nt)
    # straighten may have nudged the anchor (the Group Output): move everything back by as much,
    # so the tree stays where it was and a second format finds it in the same place
    a = nt.nodes[f.anchor].location_absolute
    dx, dy = a[0] - anchor[0], a[1] - anchor[1]
    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        for n in nt.nodes:
            if n.bl_idname != 'NodeFrame':
                x, y = n.location_absolute
                n.location_absolute = (x - dx, y - dy)
        editor.redraw()
    return made, copies, f, st


def format_tree(nt, mode='relayout', editor=None, duplicates=True, swaps=True, cfg=None):
    """Format one tree in place, with the rules and options of cfg (rules.Config; default: all
    rules, one deterministic pass). On any logic difference the tree is restored and
    LogicChanged raised. Returns a dict of stats."""
    cfg = cfg or rules.Config()
    with rules.applied(cfg):
        return _format_tree(nt, mode, editor, duplicates, swaps, cfg)


def _format_tree(nt, mode, editor, duplicates, swaps, cfg):
    """format_tree with the layout parameters of cfg set."""
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
        for k in range(6):
            sig = _signature(nt)
            try:
                made, c, f, ost = format_once(nt, mode, editor, duplicates, swaps, cfg)
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
    own = editor is None
    editor = editor or Editor()
    try:
        editor.show(nt)
        if ortho.count(nt):
            return False
        snap = check.Snapshot(nt)
        sig = _signature(nt)
        try:
            format_tree(nt, mode, editor, cfg=cfg)
            editor.show(nt)
            new = _signature(nt)
        finally:
            snap.restore(nt, editor)
            editor.redraw()
        return same_layout(new, sig)
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
    """The rules tree nt breaks, as lint.Violations (code, name, message, x, y with y up), for
    the enabled rules of cfg. formatted=True also tries a format (on a snapshot, undone) and
    adds NF900 not-formatted if it would move anything. The tree is left unchanged."""
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
                out.append(lint.Violation('NF010', rules.NAMES['NF010'],
                                          "input nodes would get copies next to their distant consumers", 0.0, 0.0))
        if cfg.on('NF011'):
            out += _comm_crossings(d, model.Model(data))
        if formatted and not is_formatted(nt, mode, editor, cfg):
            out.append(lint.Violation('NF900', 'not-formatted', "formatting would change the layout", 0.0, 0.0))
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
                                      round(hit[0], 1), round(-hit[1], 1)))
    return out
