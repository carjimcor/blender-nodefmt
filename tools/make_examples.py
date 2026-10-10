# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the rule examples: one small synthetic node tree per rule that breaks it.

    blender --factory-startup --python tools/make_examples.py [-- --only NF031]

Writes examples/NF0xx.blend, each holding one Geometry Nodes group named "NF0xx <rule name>"
(with a fake user, no objects, no screens), and examples/selection.blend for Sort Selection.
Runs with Blender's window: reroutes are placed from socket positions, which only exist once a
tree is drawn. Blender closes itself.
"""
import argparse
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="make_examples.py")
ap.add_argument("--only", action="append", default=[], help="build only this example (repeatable)")
ap.add_argument("--out", default=os.path.join(ROOT, "examples"))
ARGS = ap.parse_args(argv)


class Tree:
    """A Geometry Nodes group under construction: nodes, links and orthogonal wires."""

    def __init__(self, code, inputs=(("Geometry", 'Geometry'),), outputs=(("Geometry", 'Geometry'),), name=None):
        """A new group "<code> <rule name>" (or `name`) with the given interface sockets (name,
        type)."""
        from nodefmt import rules
        self.nt = bpy.data.node_groups.new(name or f"{code} {rules.NAMES[code]}", 'GeometryNodeTree')
        self.nt.use_fake_user = True
        for name, kind in inputs:
            self.nt.interface.new_socket(name, in_out='INPUT', socket_type='NodeSocket' + kind)
        for name, kind in outputs:
            self.nt.interface.new_socket(name, in_out='OUTPUT', socket_type='NodeSocket' + kind)
        self.wires = []
        self.levels = []
        self.selected = set()  # nodes saved selected (the others are not)

    def node(self, kind, x, y, name=None, parent=None, **props):
        """Add a node of type `kind` with its top-left corner at (x, y)."""
        n = self.nt.nodes.new(kind)
        if name:
            n.name = n.label = name
        for k, v in props.items():
            setattr(n, k, v)
        if parent is not None:
            n.parent = parent
            n.location_absolute = (x, y)
        else:
            n.location = (x, y)
        return n

    def link(self, a, out, b, inp):
        """A direct link from output `out` of node a to input `inp` of node b (index or name)."""
        return self.nt.links.new(a.outputs[out], b.inputs[inp])

    def wire(self, a, out, b, inp, points):
        """A link drawn through reroutes, made in finish(). points: [(x, y, dy, label)], dy and
        label optional; y is a height, or 'src' / 'dst' (level with the source or destination
        socket) or 'bottom' (6 units below the lowest node the wire passes at x), plus dy."""
        self.wires.append((a, out, b, inp, points))

    def level(self, a, out, b, inp, move=None, dy=0.0):
        """Move node b (or `move`, a or b) up or down so input `inp` of b is level with output
        `out` of a, or dy above it (done in finish(), in the order given)."""
        self.levels.append((a, out, b, inp, move or b, dy))

    def reroute(self, x, y, label=""):
        """A reroute at (x, y)."""
        r = self.nt.nodes.new('NodeReroute')
        r.location = (x, y)
        r.label = label
        return r

    @staticmethod
    def _bottom(n):
        """The y of a node's bottom edge (at UI scale 1)."""
        return n.location_absolute[1] - n.dimensions.y

    def finish(self, editor):
        """Draw the tree, then make the wires through their reroutes."""
        from nodefmt.sockets import socket_location
        editor.show(self.nt)
        editor.redraw()
        for n in self.nt.nodes:  # a Group Input shows only the sockets it feeds
            if n.bl_idname == 'NodeGroupInput':
                for s in n.outputs:
                    s.hide = not s.is_linked and not any(w[0] == n and n.outputs[w[1]] == s for w in self.wires)
        editor.redraw()
        for a, out, b, inp, move, off in self.levels:
            dy = socket_location(a.outputs[out])[1] + off - socket_location(b.inputs[inp])[1]
            dy = dy if move == b else -dy
            move.location_absolute = (move.location_absolute[0], move.location_absolute[1] + dy)
            editor.redraw()
        for a, out, b, inp, points in self.wires:
            src, dst = a.outputs[out], b.inputs[inp]
            sy, dy = socket_location(src)[1], socket_location(dst)[1]
            prev = src
            xs = [p[0] for p in points]
            for p in points:
                if p[1] == 'bottom':
                    y = min(self._bottom(n) for n in self.nt.nodes
                            if n.bl_idname not in ('NodeReroute', 'NodeFrame') and n not in (a, b)
                            and n.location_absolute[0] < max(xs)
                            and n.location_absolute[0] + n.dimensions.x > min(xs)) - 6.0
                else:
                    y = sy if p[1] == 'src' else dy if p[1] == 'dst' else p[1]
                r = self.reroute(p[0], y + (p[2] if len(p) > 2 else 0.0), p[3] if len(p) > 3 else "")
                self.nt.links.new(prev, r.inputs[0])
                prev = r.outputs[0]
            self.nt.links.new(prev, dst)
        for n in self.nt.nodes:
            n.select = n in self.selected
        editor.redraw()


# ---------------------------------------------------------------- the examples
# Coordinates are node units, y up; a node's location is its top-left corner. level() lines
# sockets up exactly, so each example breaks its own rule and little else.

def chain(t, nodes):
    """Link the first output of each node to the first input of the next, level."""
    for a, b in zip(nodes, nodes[1:]):
        t.link(a, 0, b, 0)
        t.level(a, 0, b, 0)


def nf001():
    """Curved links: Set Position sits lower than the nodes it connects."""
    t = Tree("NF001")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 240, -140)
    go = t.node('NodeGroupOutput', 480, -20)
    t.link(gi, 0, sp, 0)
    t.link(sp, 0, go, 0)
    return t


def nf002():
    """A wire behind a node: the Value wire runs straight through Transform."""
    t = Tree("NF002", inputs=(("Geometry", 'Geometry'), ("Value", 'Float')))
    gi = t.node('NodeGroupInput', 0, 0)
    tr = t.node('GeometryNodeTransform', 240, 0)
    sp = t.node('GeometryNodeSetPosition', 520, 0)
    go = t.node('NodeGroupOutput', 740, 0)
    chain(t, [gi, tr, sp, go])
    t.wire(gi, 1, sp, "Offset", [(460, 'src'), (460, 'dst')])
    return t


def nf003():
    """Almost straight: the reroute is 1.5 units off the line of its wire."""
    t = Tree("NF003")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 400, 0)
    go = t.node('NodeGroupOutput', 620, 0)
    t.level(gi, 0, sp, 0)
    t.wire(gi, 0, sp, 0, [(260, 'src', 1.5)])
    chain(t, [sp, go])
    return t


def nf004():
    """Two wires that cross turn at the same spot: their reroutes sit 4 units apart."""
    t = Tree("NF004", inputs=(("A", 'Float'), ("B", 'Float')), outputs=(("Vector", 'Vector'),))
    gi = t.node('NodeGroupInput', 0, 0)
    cx = t.node('ShaderNodeCombineXYZ', 400, 0)
    go = t.node('NodeGroupOutput', 620, 0)
    t.level(gi, 0, cx, 0)
    t.wire(gi, 0, cx, 1, [(300, 'src'), (300, 'dst')])
    t.wire(gi, 1, cx, 0, [(304, 'src'), (304, 'dst')])
    chain(t, [cx, go])
    return t


def nf010():
    """One Group Input feeds a node far to the right through a long wire."""
    t = Tree("NF010", inputs=(("Geometry", 'Geometry'), ("Scale", 'Float')))
    gi = t.node('NodeGroupInput', 0, 0)
    sd = t.node('GeometryNodeSubdivideMesh', 220, 0)
    sp = t.node('GeometryNodeSetPosition', 440, 0)
    tr = t.node('GeometryNodeTransform', 660, 0)
    go = t.node('NodeGroupOutput', 900, 0)
    chain(t, [gi, sd, sp, tr, go])
    t.wire(gi, 1, tr, "Scale", [(180, 'src'), (180, 'bottom', -40), (620, 'bottom', -40), (620, 'dst')])
    return t


def nf011():
    """The wires into the two inputs of an Add cross: X goes to the lower input, Y to the upper."""
    t = Tree("NF011", inputs=(), outputs=(("Value", 'Float'),))
    pos = t.node('GeometryNodeInputPosition', 0, 0)
    sep = t.node('ShaderNodeSeparateXYZ', 200, 0)
    add = t.node('ShaderNodeMath', 520, 0, operation='ADD')
    go = t.node('NodeGroupOutput', 740, 0)
    t.link(pos, 0, sep, 0)
    t.level(pos, 0, sep, 0)
    t.level(sep, 0, add, 0, dy=40)
    t.wire(sep, 0, add, 1, [(440, 'src'), (440, 'dst')])
    t.wire(sep, 1, add, 0, [(400, 'src'), (400, 'dst')])
    t.link(add, 0, go, 0)
    t.level(add, 0, go, 0)
    return t


def nf020():
    """The output of a Repeat zone is level with its input, so the wire into it bends."""
    t = Tree("NF020")
    gi = t.node('NodeGroupInput', 0, 0)
    rin = t.node('GeometryNodeRepeatInput', 200, 0)
    rout = t.node('GeometryNodeRepeatOutput', 760, 0)
    rin.pair_with_output(rout)
    ip = t.node('GeometryNodeInstanceOnPoints', 420, 0)
    cu = t.node('GeometryNodeMeshCube', 180, -170)
    go = t.node('NodeGroupOutput', 980, 0)
    t.link(gi, 0, rin, "Geometry")
    t.level(gi, 0, rin, "Geometry")
    t.link(rin, "Geometry", ip, 0)
    t.level(rin, "Geometry", ip, 0)
    t.wire(cu, 0, ip, "Instance", [(380, 'src'), (380, 'dst')])
    t.level(rin, "Geometry", rout, "Geometry")
    t.wire(ip, 0, rout, "Geometry", [(720, 'src'), (720, 'dst')])
    t.link(rout, "Geometry", go, 0)
    t.level(rout, "Geometry", go, 0)
    return t


def nf021():
    """A frame with nothing linked into it sits far to the left of the node it feeds."""
    t = Tree("NF021")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 220, 0)
    sd = t.node('GeometryNodeSubdivideMesh', 440, 0)
    tri = t.node('GeometryNodeTriangulate', 660, 0)
    mp = t.node('GeometryNodeMeshToPoints', 880, 0)
    ip = t.node('GeometryNodeInstanceOnPoints', 1100, 0)
    go = t.node('NodeGroupOutput', 1320, 0)
    chain(t, [gi, sp, sd, tri, mp, ip, go])
    fr = t.nt.nodes.new('NodeFrame')
    fr.label = "Cube"
    cu = t.node('GeometryNodeMeshCube', 0, -260, parent=fr)
    tr = t.node('GeometryNodeTransform', 200, -260, parent=fr)
    sc = t.node('GeometryNodeScaleElements', 420, -260, parent=fr)
    chain(t, [cu, tr, sc])
    t.wire(sc, 0, ip, "Instance", [(1060, 'src'), (1060, 'dst')])
    return t


def nf030():
    """The wires that leave Separate XYZ cross each other, and so do the wires into Combine XYZ:
    the nodes in between are in the wrong order."""
    t = Tree("NF030", inputs=(), outputs=(("Vector", 'Vector'),))
    pos = t.node('GeometryNodeInputPosition', 0, 0)
    sep = t.node('ShaderNodeSeparateXYZ', 200, 0)
    ms = [t.node('ShaderNodeMath', 460, y, operation='MULTIPLY') for y in (60, -100, -260)]
    cx = t.node('ShaderNodeCombineXYZ', 760, 0)
    go = t.node('NodeGroupOutput', 960, 0)
    t.link(pos, 0, sep, 0)
    t.level(pos, 0, sep, 0)
    for k in range(3):  # output k feeds the node of row 2 - k, which feeds input k
        r = ms[2 - k]
        t.wire(sep, k, r, 0, [(340 + 20 * k, 'src'), (340 + 20 * k, 'dst')])
        t.wire(r, 0, cx, k, [(720 - 20 * k, 'src'), (720 - 20 * k, 'dst')])
    t.link(cx, 0, go, 0)
    t.level(cx, 0, go, 0)
    return t


def nf031():
    """A U-jog: the wire climbs over nothing and comes back down."""
    t = Tree("NF031")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 420, 0)
    go = t.node('NodeGroupOutput', 640, 0)
    t.level(gi, 0, sp, 0)
    t.wire(gi, 0, sp, 0, [(200, 'src'), (200, 'src', 80), (340, 'src', 80), (340, 'dst')])
    chain(t, [sp, go])
    return t


def nf032():
    """A wire runs along the bottom edge of Transform, 6 units below it."""
    t = Tree("NF032", inputs=(("Geometry", 'Geometry'), ("Value", 'Float')))
    gi = t.node('NodeGroupInput', 0, 0)
    tr = t.node('GeometryNodeTransform', 240, 0)
    sp = t.node('GeometryNodeSetPosition', 520, 0)
    go = t.node('NodeGroupOutput', 740, 0)
    chain(t, [gi, tr, sp, go])
    t.wire(gi, 1, sp, "Offset", [(200, 'src'), (200, 'bottom'), (460, 'bottom'), (460, 'dst')])
    return t


def nf033():
    """The Value wire goes over the Geometry wire and crosses it twice; under Transform it would
    not cross at all."""
    t = Tree("NF033", inputs=(("Geometry", 'Geometry'), ("Value", 'Float')))
    gi = t.node('NodeGroupInput', 0, 0)
    tr = t.node('GeometryNodeTransform', 240, 0)
    sp = t.node('GeometryNodeSetPosition', 520, 0)
    go = t.node('NodeGroupOutput', 740, 0)
    chain(t, [gi, tr, sp, go])
    t.wire(gi, 1, sp, "Offset", [(180, 'src'), (180, 'src', 100), (460, 'src', 100), (460, 'dst')])
    return t


def nf034():
    """A reroute in the middle of a straight wire looks like a junction."""
    t = Tree("NF034")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 400, 0)
    go = t.node('NodeGroupOutput', 620, 0)
    t.level(gi, 0, sp, 0)
    t.wire(gi, 0, sp, 0, [(260, 'src')])
    chain(t, [sp, go])
    return t


def nf040():
    """The label "Offset" is on the second reroute of its wire, not the first."""
    t = Tree("NF040", inputs=(("Geometry", 'Geometry'), ("Value", 'Float')))
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 480, 0)
    go = t.node('NodeGroupOutput', 700, 0)
    chain(t, [gi, sp, go])
    t.wire(gi, 1, sp, "Offset", [(420, 'src'), (420, 'dst', 0.0, "Offset")])
    return t


def selection():
    """For Sort Selection: a messy frame "Sort me" in a sorted tree, linked to the rest on both
    sides (a Value node feeds it, Join Geometry takes two of its outputs). The frame is selected."""
    t = Tree("selection", name="Sort selection")
    gi = t.node('NodeGroupInput', 0, 0)
    sp = t.node('GeometryNodeSetPosition', 220, 0)
    val = t.node('ShaderNodeValue', 220, -240)
    fr = t.nt.nodes.new('NodeFrame')
    fr.label = "Sort me"
    tr = t.node('GeometryNodeTransform', 560, -80, parent=fr)
    sd = t.node('GeometryNodeSubdivideMesh', 820, 40, parent=fr)
    tri = t.node('GeometryNodeTriangulate', 760, -260, parent=fr)
    mp = t.node('GeometryNodeMeshToPoints', 1160, 0)
    jo = t.node('GeometryNodeJoinGeometry', 1400, 0)
    go = t.node('NodeGroupOutput', 1600, 0)
    chain(t, [gi, sp])
    t.link(sp, 0, tr, 0)
    t.link(val, 0, tr, "Scale")
    t.link(tr, 0, sd, 0)
    t.link(sd, 0, tri, 0)
    t.link(tri, 0, mp, 0)
    t.link(mp, 0, jo, 0)
    t.link(sd, 0, jo, 0)
    chain(t, [jo, go])
    t.selected = {fr}
    return t


EXTRAS = {"selection": selection}  # examples for other tests (not of a rule)

EXAMPLES = {"NF001": nf001, "NF002": nf002, "NF003": nf003, "NF004": nf004, "NF010": nf010,
            "NF011": nf011, "NF020": nf020, "NF021": nf021, "NF030": nf030, "NF031": nf031,
            "NF032": nf032, "NF033": nf033, "NF034": nf034, "NF040": nf040}


def main():
    """Build every example (or the --only ones) and write each to its own file."""
    from nodefmt.draw import Editor
    bpy.context.preferences.view.ui_scale = 1.0  # in memory only: positions are made at scale 1
    os.makedirs(ARGS.out, exist_ok=True)
    ed = Editor()
    try:
        for code, make in {**EXAMPLES, **EXTRAS}.items():
            if ARGS.only and code not in ARGS.only:
                continue
            t = make()
            t.finish(ed)
            path = os.path.join(ARGS.out, f"{code}.blend")
            bpy.data.libraries.write(path, {t.nt}, fake_user=True, compress=True)
            print(f"wrote {os.path.relpath(path, ROOT)}: {t.nt.name}", flush=True)
    finally:
        ed.close()


def tick():
    """Run main() once Blender's window is up, then quit."""
    code = 0
    try:
        main()
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
