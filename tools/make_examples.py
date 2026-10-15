# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the rule examples: one small synthetic node tree per rule that breaks it.

    blender --factory-startup --python tools/make_examples.py [-- --only NF031 ... --out DIR]

Writes examples/NF0xx.blend, each holding one Geometry Nodes group "NF0xx <rule name>" (fake
user, no objects, no screens); NF0xx-<what>.blend is a second example of a rule (group "NF0xx
<rule name> (<what>)") and selection.blend is for Sort Selection. A style rule's example is saved
sorted with every style rule off (see main()). An example meant for another UI scale stores it
in the group's custom property "nodefmt_ui_scale" (NF003-rows: 1.4, NF034: 1.25). Runs with
Blender's window (reroutes are placed from socket positions, which only exist once a tree is
drawn) and closes itself.
"""

import argparse
import os
import sys
import traceback
from itertools import pairwise

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="make_examples.py")
ap.add_argument("--only", action="append", default=[], help="build only this example (repeatable)")
ap.add_argument("--out", default=os.path.join(ROOT, "examples"))
ARGS = ap.parse_args(argv)


SCALE_KEY = "nodefmt_ui_scale"  # custom property: the UI scale an example is made for (default 1)


class Tree:
    """A Geometry Nodes group under construction: nodes, links and orthogonal wires."""

    def __init__(self, code, inputs=(("Geometry", "Geometry"),), outputs=(("Geometry", "Geometry"),), name=None):
        """A new group "<code> <rule name>" (or `name`) with the given interface sockets (name,
        type)."""
        from nodefmt import rules

        self.nt = bpy.data.node_groups.new(name or f"{code} {rules.NAMES[code]}", "GeometryNodeTree")
        self.nt.use_fake_user = True
        for sock, kind in inputs:
            self.nt.interface.new_socket(sock, in_out="INPUT", socket_type="NodeSocket" + kind)
        for sock, kind in outputs:
            self.nt.interface.new_socket(sock, in_out="OUTPUT", socket_type="NodeSocket" + kind)
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
        r = self.nt.nodes.new("NodeReroute")
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
            if n.bl_idname == "NodeGroupInput":
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
                if p[1] == "bottom":
                    y = (
                        min(
                            self._bottom(n)
                            for n in self.nt.nodes
                            if n.bl_idname not in ("NodeReroute", "NodeFrame")
                            and n not in (a, b)
                            and n.location_absolute[0] < max(xs)
                            and n.location_absolute[0] + n.dimensions.x > min(xs)
                        )
                        - 6.0
                    )
                else:
                    y = sy if p[1] == "src" else dy if p[1] == "dst" else p[1]
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
    for a, b in pairwise(nodes):
        t.link(a, 0, b, 0)
        t.level(a, 0, b, 0)


def nf001():
    """Curved links: Set Position sits lower than the nodes it connects."""
    t = Tree("NF001")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 240, -140)
    go = t.node("NodeGroupOutput", 480, -20)
    t.link(gi, 0, sp, 0)
    t.link(sp, 0, go, 0)
    return t


def nf002():
    """A wire behind a node: the Value wire runs straight through Transform."""
    t = Tree("NF002", inputs=(("Geometry", "Geometry"), ("Value", "Float")))
    gi = t.node("NodeGroupInput", 0, 0)
    tr = t.node("GeometryNodeTransform", 240, 0)
    sp = t.node("GeometryNodeSetPosition", 520, 0)
    go = t.node("NodeGroupOutput", 740, 0)
    chain(t, [gi, tr, sp, go])
    t.wire(gi, 1, sp, "Offset", [(460, "src"), (460, "dst")])
    return t


def frame(t, label):
    """A new frame with a label."""
    fr = t.nt.nodes.new("NodeFrame")
    fr.label = label
    return fr


def nf003_rows():
    """A tall Instance on Points above y = 0, for UI scale 1.4: Multiply feeds its Scale (low on
    the node) straight. At a fractional scale Blender draws a node's rows above y = 0 a pixel
    taller than below it, so Scale measured elsewhere is 4 units off and its wire gets a tiny
    step. The Points wire is 1.5 units off its line (the rule broken)."""
    t = Tree("NF003", inputs=(("Geometry", "Geometry"), ("Size", "Float")), name="NF003 orthogonal-segments (rows)")
    t.nt[SCALE_KEY] = 1.4
    gi = t.node("NodeGroupInput", 0, 600)
    cu = t.node("GeometryNodeMeshCube", 200, 1000)
    mul = t.node("ShaderNodeMath", 220, 420, operation="MULTIPLY")
    ip = t.node("GeometryNodeInstanceOnPoints", 440, 600)
    go = t.node("NodeGroupOutput", 660, 600)
    t.level(gi, 0, ip, 0)
    t.wire(gi, 0, ip, 0, [(300, "src", 1.5)])
    t.link(cu, 0, ip, "Instance")
    t.link(gi, 1, mul, 0)
    t.link(mul, 0, ip, "Scale")
    t.level(mul, 0, ip, "Scale", move=mul)
    t.link(ip, 0, go, 0)
    t.level(ip, 0, go, 0)
    return t


def nf003():
    """Almost straight: the reroute is 1.5 units off the line of its wire."""
    t = Tree("NF003")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 400, 0)
    go = t.node("NodeGroupOutput", 620, 0)
    t.level(gi, 0, sp, 0)
    t.wire(gi, 0, sp, 0, [(260, "src", 1.5)])
    chain(t, [sp, go])
    return t


def nf004():
    """Two wires that cross turn at the same spot: their reroutes sit 4 units apart."""
    t = Tree("NF004", inputs=(("A", "Float"), ("B", "Float")), outputs=(("Vector", "Vector"),))
    gi = t.node("NodeGroupInput", 0, 0)
    cx = t.node("ShaderNodeCombineXYZ", 400, 0)
    go = t.node("NodeGroupOutput", 620, 0)
    t.level(gi, 0, cx, 0)
    t.wire(gi, 0, cx, 1, [(300, "src"), (300, "dst")])
    t.wire(gi, 1, cx, 0, [(304, "src"), (304, "dst")])
    chain(t, [cx, go])
    return t


def nf005():
    """A messy tree: nodes out of order, links curved and crossing. The tree computes the same
    before and after the sort."""
    t = Tree("NF005", inputs=(("Geometry", "Geometry"), ("Height", "Float")))
    gi = t.node("NodeGroupInput", 300, -260)
    sd = t.node("GeometryNodeSubdivideMesh", 0, 0)
    val = t.node("ShaderNodeValue", 620, -300)
    val.outputs[0].default_value = 0.5
    mul = t.node("ShaderNodeMath", 260, 40, operation="MULTIPLY")
    cx = t.node("ShaderNodeCombineXYZ", 860, -180)
    sp = t.node("GeometryNodeSetPosition", 520, 60)
    cu = t.node("GeometryNodeMeshCube", 40, -360)
    jo = t.node("GeometryNodeJoinGeometry", 900, 40)
    go = t.node("NodeGroupOutput", 1100, -120)
    t.link(gi, 0, sd, 0)
    t.link(gi, 1, mul, 0)
    t.link(val, 0, mul, 1)
    t.link(mul, 0, cx, 2)
    t.link(sd, 0, sp, 0)
    t.link(cx, 0, sp, "Offset")
    t.link(sp, 0, jo, 0)
    t.link(cu, 0, jo, 0)
    t.link(jo, 0, go, 0)
    return t


def nf010():
    """One Group Input feeds a node far to the right through a long wire."""
    t = Tree("NF010", inputs=(("Geometry", "Geometry"), ("Scale", "Float")))
    gi = t.node("NodeGroupInput", 0, 0)
    sd = t.node("GeometryNodeSubdivideMesh", 220, 0)
    sp = t.node("GeometryNodeSetPosition", 440, 0)
    tr = t.node("GeometryNodeTransform", 660, 0)
    go = t.node("NodeGroupOutput", 900, 0)
    chain(t, [gi, sd, sp, tr, go])
    t.wire(gi, 1, tr, "Scale", [(180, "src"), (180, "bottom", -40), (620, "bottom", -40), (620, "dst")])
    return t


def nf011():
    """The wires into the two inputs of an Add cross: X goes to the lower input, Y to the upper."""
    t = Tree("NF011", inputs=(), outputs=(("Value", "Float"),))
    pos = t.node("GeometryNodeInputPosition", 0, 0)
    sep = t.node("ShaderNodeSeparateXYZ", 200, 0)
    add = t.node("ShaderNodeMath", 520, 0, operation="ADD")
    go = t.node("NodeGroupOutput", 740, 0)
    t.link(pos, 0, sep, 0)
    t.level(pos, 0, sep, 0)
    t.level(sep, 0, add, 0, dy=40)
    t.wire(sep, 0, add, 1, [(440, "src"), (440, "dst")])
    t.wire(sep, 1, add, 0, [(400, "src"), (400, "dst")])
    t.link(add, 0, go, 0)
    t.level(add, 0, go, 0)
    return t


def nf011_frame():
    """Zeta and Alpha (in the order of the Group Input's sockets) feed the Add in frame "Sum",
    Alpha the upper input: the frame is laid out first and cannot see where its wires come
    from."""
    t = Tree(
        "NF011",
        inputs=(("Z", "Float"), ("A", "Float")),
        outputs=(("Sum", "Float"),),
        name="NF011 commutative-swaps (frame)",
    )
    gi = t.node("NodeGroupInput", 0, 0)
    z = t.node("ShaderNodeMath", 220, 0, name="Zeta", operation="MULTIPLY")
    a = t.node("ShaderNodeMath", 220, -200, name="Alpha", operation="MULTIPLY")
    t.link(gi, 0, z, 0)
    t.link(gi, 1, a, 0)
    fr = frame(t, "Sum")
    add = t.node("ShaderNodeMath", 500, -100, parent=fr, operation="ADD")
    fin = t.node("ShaderNodeMath", 720, -100, parent=fr, operation="MULTIPLY")
    val = t.node("ShaderNodeValue", 300, -300, name="Weight", parent=fr)
    mul = t.node("ShaderNodeMath", 500, -300, parent=fr, operation="MULTIPLY")
    go = t.node("NodeGroupOutput", 950, 0)
    t.link(add, 0, fin, 0)
    t.link(val, 0, mul, 0)
    t.link(mul, 0, fin, 1)
    t.link(z, 0, add, 1)
    t.link(a, 0, add, 0)
    t.link(fin, 0, go, 0)
    return t


def nf011_zone():
    """In a Repeat zone, frame "Step" holds an Add of Omega (the iteration, doubled) and Alpha
    (from outside the zone), Alpha the upper input."""
    t = Tree(
        "NF011",
        inputs=(("Geometry", "Geometry"), ("A", "Float")),
        outputs=(("Geometry", "Geometry"),),
        name="NF011 commutative-swaps (zone)",
    )
    gi = t.node("NodeGroupInput", 0, 0)
    a = t.node("ShaderNodeMath", 220, -200, name="Alpha", operation="MULTIPLY")
    rin = t.node("GeometryNodeRepeatInput", 450, 0)
    rout = t.node("GeometryNodeRepeatOutput", 1500, 0)
    rin.pair_with_output(rout)
    om = t.node("ShaderNodeMath", 650, -50, name="Omega", operation="MULTIPLY")
    fr = frame(t, "Step")
    add = t.node("ShaderNodeMath", 850, -150, parent=fr, operation="ADD")
    cx = t.node("ShaderNodeCombineXYZ", 1050, -150, parent=fr)
    sp = t.node("GeometryNodeSetPosition", 1250, 0)
    go = t.node("NodeGroupOutput", 1700, 0)
    t.link(gi, 1, a, 0)
    t.link(gi, 0, rin, "Geometry")
    t.link(rin, "Geometry", sp, 0)
    t.link(rin, "Iteration", om, 0)
    t.link(om, 0, add, 1)
    t.link(a, 0, add, 0)
    t.link(add, 0, cx, 2)
    t.link(cx, 0, sp, "Offset")
    t.link(sp, 0, rout, "Geometry")
    t.link(rout, "Geometry", go, 0)
    return t


def nf020():
    """The output of a Repeat zone is level with its input, so the wire into it bends."""
    t = Tree("NF020")
    gi = t.node("NodeGroupInput", 0, 0)
    rin = t.node("GeometryNodeRepeatInput", 200, 0)
    rout = t.node("GeometryNodeRepeatOutput", 760, 0)
    rin.pair_with_output(rout)
    ip = t.node("GeometryNodeInstanceOnPoints", 420, 0)
    cu = t.node("GeometryNodeMeshCube", 180, -170)
    go = t.node("NodeGroupOutput", 980, 0)
    t.link(gi, 0, rin, "Geometry")
    t.level(gi, 0, rin, "Geometry")
    t.link(rin, "Geometry", ip, 0)
    t.level(rin, "Geometry", ip, 0)
    t.wire(cu, 0, ip, "Instance", [(380, "src"), (380, "dst")])
    t.level(rin, "Geometry", rout, "Geometry")
    t.wire(ip, 0, rout, "Geometry", [(720, "src"), (720, "dst")])
    t.link(rout, "Geometry", go, 0)
    t.level(rout, "Geometry", go, 0)
    return t


def nf021():
    """A frame with nothing linked into it feeds Instance on Points at the end of the tree."""
    t = Tree("NF021")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 220, 0)
    mp = t.node("GeometryNodeMeshToPoints", 440, 0)
    ip = t.node("GeometryNodeInstanceOnPoints", 660, 0)
    go = t.node("NodeGroupOutput", 880, 0)
    chain(t, [gi, sp, mp, ip, go])
    fr = t.nt.nodes.new("NodeFrame")
    fr.label = "Cube"
    cu = t.node("GeometryNodeMeshCube", 0, -260, parent=fr)
    tr = t.node("GeometryNodeTransform", 210, -260, parent=fr)
    sc = t.node("GeometryNodeScaleElements", 420, -260, parent=fr)
    chain(t, [cu, tr, sc])
    t.wire(sc, 0, ip, "Instance", [(620, "src"), (620, "dst")])
    return t


def nf021_alone():
    """Frame "Cube" feeds Instance on Points late in a long row; frame "Test" is linked to
    nothing."""
    t = Tree("NF021", name="NF021 blocks-next-to-consumer (nothing linked)")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 220, 0)
    sd = t.node("GeometryNodeSubdivideMesh", 440, 0)
    mp = t.node("GeometryNodeMeshToPoints", 660, 0)
    ip = t.node("GeometryNodeInstanceOnPoints", 880, 0)
    ri = t.node("GeometryNodeRealizeInstances", 1100, 0)
    tf = t.node("GeometryNodeTransform", 1320, 0)
    go = t.node("NodeGroupOutput", 1540, 0)
    chain(t, [gi, sp, sd, mp, ip, ri, tf, go])
    fr = frame(t, "Cube")
    cu = t.node("GeometryNodeMeshCube", 0, -260, parent=fr)
    tr = t.node("GeometryNodeTransform", 210, -260, parent=fr)
    sc = t.node("GeometryNodeScaleElements", 420, -260, parent=fr)
    chain(t, [cu, tr, sc])
    t.wire(sc, 0, ip, "Instance", [(620, "src"), (620, "dst")])
    fn = frame(t, "Test")
    va = t.node("ShaderNodeValue", 0, -600, parent=fn)
    m1 = t.node("ShaderNodeMath", 200, -600, parent=fn, operation="MULTIPLY")
    m2 = t.node("ShaderNodeMath", 400, -600, parent=fn, operation="POWER")
    t.link(va, 0, m1, 0)
    t.link(m1, 0, m2, 0)
    return t


def nf022():
    """A short and a long chain of Math nodes, both using inputs A and B, converge on one
    Divide."""
    t = Tree("NF022", inputs=(("A", "Float"), ("B", "Float")), outputs=(("Value", "Float"),))
    gi = t.node("NodeGroupInput", 0, 0)
    short = t.node("ShaderNodeMath", 220, 0, operation="SUBTRACT")
    c1 = t.node("ShaderNodeMath", 220, -200, operation="SUBTRACT")
    c2 = t.node("ShaderNodeMath", 440, -200, operation="SUBTRACT")
    c3 = t.node("ShaderNodeMath", 660, -200, operation="SUBTRACT")
    div = t.node("ShaderNodeMath", 880, 0, operation="DIVIDE")
    go = t.node("NodeGroupOutput", 1100, 0)
    t.link(gi, 1, short, 0)
    t.link(gi, 0, short, 1)
    t.link(gi, 1, c1, 0)
    t.link(gi, 0, c1, 1)
    t.link(c1, 0, c2, 0)
    t.link(gi, 1, c2, 1)
    t.link(c2, 0, c3, 0)
    t.link(gi, 1, c3, 1)
    t.link(short, 0, div, 0)
    t.link(c3, 0, div, 1)
    t.link(div, 0, go, 0)
    return t


def nf023():
    """Index -> Compare feeds the Selection of Store Named Attribute and Position -> Length its
    Value; with the rule off both chains sit at the far left of the tree."""
    t = Tree("NF023")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 220, 0)
    mp = t.node("GeometryNodeMeshToPoints", 440, 0)
    st = t.node("GeometryNodeStoreNamedAttribute", 660, 0)
    go = t.node("NodeGroupOutput", 880, 0)
    chain(t, [gi, sp, mp, st, go])
    ix = t.node("GeometryNodeInputIndex", 0, -260)
    cmp = t.node("FunctionNodeCompare", 200, -260, data_type="INT", operation="EQUAL")
    t.link(ix, 0, cmp, "A")
    t.link(cmp, 0, st, "Selection")
    po = t.node("GeometryNodeInputPosition", 0, -460)
    ln = t.node("ShaderNodeVectorMath", 200, -460, operation="LENGTH")
    t.link(po, 0, ln, 0)
    t.link(ln, "Value", st, "Value")
    return t


def nf035():
    """Three Grids feed one Join Geometry; with the rule off their wires arrive a slot (5 units)
    apart, packed together right before the socket."""
    t = Tree("NF035", inputs=())
    grids = [t.node("GeometryNodeMeshGrid", 0, y) for y in (0, -220, -440)]
    jo = t.node("GeometryNodeJoinGeometry", 260, -220)
    go = t.node("NodeGroupOutput", 460, -220)
    for g in grids:
        t.link(g, 0, jo, 0)
    t.link(jo, 0, go, 0)
    return t


def nf035_strings():
    """Join Strings with its Delimiter linked too: the fan of its three Strings keeps clear of the
    Delimiter wire just above them."""
    t = Tree(
        "NF035",
        inputs=(("Separator", "String"), ("First", "String"), ("Second", "String"), ("Third", "String")),
        outputs=(("Text", "String"),),
        name="NF035 fanned-multi-inputs (strings)",
    )
    gi = t.node("NodeGroupInput", 0, 0)
    js = t.node("GeometryNodeStringJoin", 260, 0)
    go = t.node("NodeGroupOutput", 460, 0)
    t.link(gi, 0, js, "Delimiter")
    for k in (3, 2, 1):  # the last link made takes the top slot
        t.link(gi, k, js, "Strings")
    t.link(js, 0, go, 0)
    return t


def nf030():
    """Combine XYZ and Separate XYZ both feed the Group Output; with Combine XYZ lower, the two
    wires into the Group Output cross."""
    t = Tree("NF030", inputs=(("Size", "Float"),), outputs=(("Scale", "Vector"), ("X", "Float")))
    gi = t.node("NodeGroupInput", 0, 0)
    sep = t.node("ShaderNodeSeparateXYZ", 260, 20)
    cx = t.node("ShaderNodeCombineXYZ", 460, 0)
    go = t.node("NodeGroupOutput", 660, 0)
    t.link(gi, 0, sep, 0)
    for k in (1, 0, 2):
        t.link(gi, 0, cx, k)
    t.link(cx, 0, go, 0)
    t.link(sep, 0, go, 1)
    return t


def nf031():
    """The Height wire climbs over Separate XYZ and comes back down to Combine XYZ."""
    t = Tree(
        "NF031",
        inputs=(("Height", "Float"), ("Width", "Float"), ("Position", "Vector")),
        outputs=(("Difference", "Float"), ("Size", "Vector")),
    )
    gi = t.node("NodeGroupInput", 0, -100)
    sep = t.node("ShaderNodeSeparateXYZ", 220, -120)
    sub = t.node("ShaderNodeMath", 440, 0, operation="SUBTRACT")
    cx = t.node("ShaderNodeCombineXYZ", 440, -180)
    go = t.node("NodeGroupOutput", 660, 0)
    t.link(gi, 2, sep, 0)
    t.link(gi, 1, cx, 1)
    t.link(gi, 0, cx, 2)
    t.link(sep, 0, sub, 0)
    t.link(sep, 2, sub, 1)
    t.link(sub, 0, go, 0)
    t.link(cx, 0, go, 1)
    return t


def nf032():
    """In a Repeat zone, the Offset wire from outside runs along the bottom of the zone's
    outline to the Add inside."""
    t = Tree(
        "NF032",
        inputs=(("Geometry", "Geometry"), ("Count", "Int"), ("Offset", "Float")),
        outputs=(("Geometry", "Geometry"), ("Value", "Float")),
    )
    gi = t.node("NodeGroupInput", 0, 0)
    rin = t.node("GeometryNodeRepeatInput", 220, 0)
    rout = t.node("GeometryNodeRepeatOutput", 880, 0)
    rin.pair_with_output(rout)
    rout.repeat_items.new("FLOAT", "Value")
    mul = t.node("ShaderNodeMath", 440, -160, operation="MULTIPLY")
    add = t.node("ShaderNodeMath", 660, -230, operation="ADD")
    sub = t.node("ShaderNodeMath", 1100, -150, operation="SUBTRACT")
    go = t.node("NodeGroupOutput", 1320, 0)
    t.link(gi, 1, rin, "Iterations")
    t.link(gi, 0, rin, "Geometry")
    t.link(rin, "Geometry", rout, "Geometry")
    t.link(rin, "Iteration", mul, 0)
    t.link(rin, "Iteration", mul, 1)
    t.link(mul, 0, add, 0)
    t.link(gi, 2, add, 1)
    t.link(add, 0, rout, "Value")
    t.link(rout, "Geometry", go, 0)
    t.link(rout, "Value", sub, 0)
    t.link(gi, 2, sub, 1)
    t.link(sub, 0, go, 1)
    return t


def nf033():
    """The Value wire goes over the Geometry wire and crosses it twice; under Transform it would
    not cross at all."""
    t = Tree("NF033", inputs=(("Geometry", "Geometry"), ("Value", "Float")))
    gi = t.node("NodeGroupInput", 0, 0)
    tr = t.node("GeometryNodeTransform", 240, 0)
    sp = t.node("GeometryNodeSetPosition", 520, 0)
    go = t.node("NodeGroupOutput", 740, 0)
    chain(t, [gi, tr, sp, go])
    t.wire(gi, 1, sp, "Offset", [(180, "src"), (180, "src", 100), (460, "src", 100), (460, "dst")])
    return t


def nf034():
    """Combine XYZ in a frame feeds Subtract from above. Shown at UI scale 1.25, where rounding
    to the pixel grid can leave a reroute in a straight run."""
    t = Tree("NF034", inputs=(("Y", "Float"), ("Z", "Float")), outputs=(("Value", "Float"),))
    t.nt[SCALE_KEY] = 1.25
    gi = t.node("NodeGroupInput", 0, 0)
    fr = t.nt.nodes.new("NodeFrame")
    cx = t.node("ShaderNodeCombineXYZ", 200, 40, parent=fr)
    sub = t.node("ShaderNodeMath", 460, -20, operation="SUBTRACT")
    go = t.node("NodeGroupOutput", 680, 0)
    t.link(gi, 0, cx, 1)
    t.link(gi, 1, cx, 2)
    t.link(gi, 1, sub, 0)
    t.link(cx, 0, sub, 1)
    t.link(sub, 0, go, 0)
    return t


def nf036():
    """Three Combine XYZ, one under the other, each fed X by a Math node level with it and Y by a
    Math node a little lower: the three Y wires turn in one gap, one above the other. Without the
    rule each takes its own track, a staircase; with it they share one x."""
    t = Tree("NF036", inputs=(), outputs=(("A", "Vector"), ("B", "Vector"), ("C", "Vector")))
    go = t.node("NodeGroupOutput", 520, 0)
    for k in range(3):
        y = -260 * k
        x = t.node("ShaderNodeMath", 0, y)
        yy = t.node("ShaderNodeMath", 0, y - 150)
        cx = t.node("ShaderNodeCombineXYZ", 260, y)
        t.link(x, 0, cx, 0)
        t.level(x, 0, cx, 0)
        t.link(yy, 0, cx, 1)
        t.link(cx, 0, go, k)
    return t


def nf040():
    """The label "Offset" is on the second reroute of its wire, not the first."""
    t = Tree("NF040", inputs=(("Geometry", "Geometry"), ("Value", "Float")))
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 480, 0)
    go = t.node("NodeGroupOutput", 700, 0)
    chain(t, [gi, sp, go])
    t.wire(gi, 1, sp, "Offset", [(420, "src"), (420, "dst", 0.0, "Offset")])
    return t


def nf041():
    """The Offset wire carries a long label and turns right before Set Position: the label, and
    the greyed copy Blender shows on the next reroute, cover the nodes beside the gap."""
    t = Tree("NF041", inputs=(("Geometry", "Geometry"), ("Offset", "Vector")))
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 240, 0)
    go = t.node("NodeGroupOutput", 460, 0)
    chain(t, [gi, sp, go])
    t.wire(gi, 1, sp, "Offset", [(200, "src", 0.0, "Offset along the normal"), (200, "dst")])
    return t


def selection():
    """For Sort Selection: a messy frame "Sort me" in a sorted tree, linked to the rest on both
    sides (a Value node feeds it, Join Geometry takes two of its outputs). The frame is selected."""
    t = Tree("selection", name="Sort selection")
    gi = t.node("NodeGroupInput", 0, 0)
    sp = t.node("GeometryNodeSetPosition", 220, 0)
    val = t.node("ShaderNodeValue", 220, -240)
    fr = t.nt.nodes.new("NodeFrame")
    fr.label = "Sort me"
    tr = t.node("GeometryNodeTransform", 560, -80, parent=fr)
    sd = t.node("GeometryNodeSubdivideMesh", 820, 40, parent=fr)
    tri = t.node("GeometryNodeTriangulate", 760, -260, parent=fr)
    mp = t.node("GeometryNodeMeshToPoints", 1160, 0)
    jo = t.node("GeometryNodeJoinGeometry", 1400, 0)
    go = t.node("NodeGroupOutput", 1600, 0)
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

# file name -> builder; a name "NF0xx-<what>" is a second example of rule NF0xx
EXAMPLES = {
    "NF001": nf001,
    "NF002": nf002,
    "NF003": nf003,
    "NF003-rows": nf003_rows,
    "NF004": nf004,
    "NF005": nf005,
    "NF010": nf010,
    "NF011": nf011,
    "NF011-frame": nf011_frame,
    "NF011-zone": nf011_zone,
    "NF020": nf020,
    "NF021": nf021,
    "NF021-alone": nf021_alone,
    "NF022": nf022,
    "NF023": nf023,
    "NF030": nf030,
    "NF031": nf031,
    "NF032": nf032,
    "NF033": nf033,
    "NF034": nf034,
    "NF035": nf035,
    "NF035-strings": nf035_strings,
    "NF036": nf036,
    "NF040": nf040,
    "NF041": nf041,
}


def main():
    """Build every example (or the --only ones) and write each to its own file. A style rule's
    example is saved sorted with every style rule off, so the file shows the rule broken the way
    the formatter leaves it when the rule is off."""
    from nodefmt import api, rules
    from nodefmt.draw import Editor

    os.makedirs(ARGS.out, exist_ok=True)
    ed = Editor()
    try:
        for code, make in {**EXAMPLES, **EXTRAS}.items():
            if ARGS.only and code not in ARGS.only:
                continue
            bpy.context.preferences.view.ui_scale = 1.0  # in memory only: positions are made at scale 1
            t = make()
            t.finish(ed)
            if code.split("-")[0] in rules.STYLE:
                bpy.context.preferences.view.ui_scale = t.nt.get(SCALE_KEY, 1.0)
                api.format_tree(t.nt, "relayout", ed, cfg=rules.Config(rules.GUARANTEES))
                for n in t.nt.nodes:
                    n.select = False
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
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
