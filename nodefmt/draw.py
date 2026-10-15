# SPDX-License-Identifier: GPL-3.0-or-later
"""Make Blender compute node sizes and socket positions by drawing a tree once.

Blender only lays out a node (its size, its socket positions) while drawing it in a node editor.
`Editor.show(tree)` puts the tree in a node editor of the current window and forces one
synchronous redraw; after it returns, node.dimensions and socket positions are valid. Needs a UI
session (not `blender -b`). `close()` puts the editor back as it was, including the group path.
"""

from itertools import pairwise

import bpy


class Editor:
    """A node editor that draws trees on demand (see the module docstring)."""

    def __init__(self, area=None):
        """Use `area` (default: a node editor of the current window, else its largest area);
        remember what it showed so close() can put it back."""
        win = bpy.context.window or bpy.context.window_manager.windows[0]
        if area is None:
            areas = [a for a in win.screen.areas if a.type == "NODE_EDITOR"]
            area = areas[0] if areas else max(win.screen.areas, key=lambda a: a.width * a.height)
        self.win, self.area = win, area
        self.ui_type = area.ui_type
        self.space = None
        self.active = None  # active object and modifiers, if show() changed them
        self.current = None  # the tree show() drew last
        if area.type == "NODE_EDITOR":
            sp = area.spaces.active
            self.space = (sp.pin, sp.node_tree, [p.node_tree for p in sp.path])

    def show(self, tree):
        """Draw `tree` as the user sees it. A Geometry Nodes tree that a modifier uses (directly or
        nested) is shown through that object and modifier with its group path, since some nodes,
        like Bake, draw more rows there; any other tree is pinned."""
        area = self.area
        if area.ui_type != tree.bl_idname:
            area.ui_type = tree.bl_idname
        space = area.spaces.active
        if space.edit_tree == tree and self.current == tree.as_pointer():
            self.redraw()
            return
        self.current = tree.as_pointer()
        hit = _modifier_path(tree) if tree.bl_idname == "GeometryNodeTree" else None
        if hit:
            vl = bpy.context.view_layer
            if self.active is None:
                self.active = (vl.objects.active, {o.name: o.modifiers.active for o in vl.objects if o.modifiers})
            o, m, path = hit
            vl.objects.active = o
            o.modifiers.active = m
            space.pin = False
            for _ in range(3):  # the editor picks up the active modifier's tree on a later redraw
                self.redraw()
                if space.node_tree == m.node_group:
                    break
            if space.node_tree == m.node_group:
                while len(space.path) > 1:  # back to the modifier's tree, then down to `tree`
                    space.path.pop()
                for parent, name in path:
                    space.path.append(parent.nodes[name].node_tree, node=parent.nodes[name])
                self.redraw()
                if space.edit_tree == tree:
                    return
        space.pin = True
        space.node_tree = tree
        self.redraw()

    def redraw(self):
        """Force one synchronous redraw of the editor, so node sizes and sockets are up to date."""
        region = next(r for r in self.area.regions if r.type == "WINDOW")
        with bpy.context.temp_override(window=self.win, area=self.area, region=region):
            bpy.ops.wm.redraw_timer(type="DRAW_WIN", iterations=1)

    def close(self):
        """Put the editor (and the active object and modifiers) back as they were."""
        if self.active is not None:
            vl = bpy.context.view_layer
            obj, mods = self.active
            for name, m in mods.items():
                o = vl.objects.get(name)
                if o is not None and m is not None:
                    o.modifiers.active = m
            vl.objects.active = obj
            self.active = None
        area = self.area
        if area.ui_type != self.ui_type:
            area.ui_type = self.ui_type
        if self.space is None or area.type != "NODE_EDITOR":
            return
        pin, tree, path = self.space
        sp = area.spaces.active
        if [p.node_tree for p in sp.path] == path and sp.pin == pin:
            return
        try:
            sp.node_tree = tree
            for parent, child in pairwise(path):
                node = next((n for n in parent.nodes if getattr(n, "node_tree", None) == child), None)
                sp.path.append(child, node=node)
        except Exception:  # noqa: BLE001, S110 - restoring the editor's path is best effort
            pass
        sp.pin = pin


def _modifier_path(tree):
    """(object, modifier, path) of the first Geometry Nodes modifier (objects by name, modifiers
    in order) whose tree is `tree` or reaches it through group nodes, else None. path: the
    shortest list of (parent tree, group node name) from the modifier's tree down to `tree`."""
    for o in sorted(bpy.context.view_layer.objects, key=lambda o: o.name):
        for m in o.modifiers:
            root = m.node_group if m.type == "NODES" else None
            if root is None:
                continue
            seen, level = {root.as_pointer()}, [(root, [])]
            while level:
                nxt = []
                for t, path in level:
                    if t == tree:
                        return o, m, path
                    for n in sorted(t.nodes, key=lambda n: n.name):
                        g = getattr(n, "node_tree", None) if n.bl_idname == "GeometryNodeGroup" else None
                        if g is not None and g.as_pointer() not in seen:
                            seen.add(g.as_pointer())
                            nxt.append((g, path + [(t, n.name)]))
                level = nxt
    return None
