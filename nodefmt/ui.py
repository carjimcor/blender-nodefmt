# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on: buttons in the Node Editor sidebar (nodefmt tab) and rule toggles in the preferences.

The rules come from a nodefmt.toml next to the .blend file (or in a folder above it) when there
is one and "Use nodefmt.toml" is on, else from the toggles (preferences, also shown in the
panel). The layout is made for the UI scale Blender runs at. Every format is one undo step.
"""
import os

import bpy

from . import api, lint, rules
from .draw import Editor

MODES = [('relayout', "Relayout", "Build a new layout from scratch: columns, order and wires"),
         ('keep', "Keep layout (experimental)", "Keep your columns and order; only straighten wires and fix reroutes")]
_LAST = {"lines": [], "tree": "", "done": False}  # the last check, shown in the panel


def _prefs(context):
    """The add-on preferences (None if the add-on is loaded some other way, e.g. by a test)."""
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def config(context):
    """The rules.Config for the buttons: nodefmt.toml if found and allowed, else the toggles."""
    p = _prefs(context)
    if p is None or p.use_config_file:
        start = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else None
        path, _ = rules.find_config(start) if start else (None, {})
        if path:
            return rules.load(start)
    if p is None:
        return rules.Config()
    on = [c for c in rules.STYLE if getattr(p, "rule_" + c, True)]
    enabled = rules.resolve(on, []) if on else rules.resolve(None, ["ALL"])
    return rules.Config(enabled, thorough=p.thorough)


def _rule_props():
    """A BoolProperty per style rule for the preferences."""
    props = {}
    for code in rules.STYLE:
        props["rule_" + code] = bpy.props.BoolProperty(
            name=f"{code} {rules.NAMES[code]}", description=rules.SHORT[code], default=True)
    return props


class NODEFMT_AddonPreferences(bpy.types.AddonPreferences):
    """Rule toggles and options (Preferences > Add-ons > nodefmt)."""
    bl_idname = __package__
    __annotations__ = {
        **_rule_props(),
        "thorough": bpy.props.BoolProperty(
            name="Thorough search", default=False,
            description="Try several layouts and keep the best (slower, rarely better)"),
        "use_config_file": bpy.props.BoolProperty(
            name="Use nodefmt.toml", default=True,
            description="Use the rules in a nodefmt.toml next to the .blend file, if there is one"),
    }

    def draw(self, context):
        """The options and one checkbox per style rule (guarantees are always on)."""
        col = self.layout.column()
        col.prop(self, "use_config_file")
        col.prop(self, "thorough")
        col.label(text="Style rules (guarantees NF001-NF005 are always on):")
        for code in rules.STYLE:
            col.prop(self, "rule_" + code)


class NODEFMT_OT_sort_tree(bpy.types.Operator):
    """Sort (format) the tree shown in the node editor."""
    bl_idname = "node.nodefmt_sort_tree"
    bl_label = "Sort Current Tree"
    bl_description = "Sort the node tree in this editor. Ctrl+Z undoes it"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Available in a node editor showing a tree of a supported type."""
        sp = context.space_data
        return sp and sp.type == 'NODE_EDITOR' and sp.edit_tree and api.formattable(sp.edit_tree)

    def execute(self, context):
        """Sort the edited tree; on a logic change it is restored and an error reported."""
        nt = context.space_data.edit_tree
        mode = context.window_manager.nodefmt_mode
        ed = Editor(context.area)
        try:
            st = api.format_tree(nt, mode, ed, cfg=config(context))
        except api.LogicChanged as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        finally:
            ed.close()
        self.report({'INFO'}, f"Sorted {api.tree_name(nt)} ({st['reroutes']} reroutes, {st['seconds']} s, "
                              f"UI scale {st['ui_scale']:g})")
        return {'FINISHED'}


class NODEFMT_OT_sort_all(bpy.types.Operator):
    """Sort (format) every node tree of the file (Geometry Nodes, shader, compositor)."""
    bl_idname = "node.nodefmt_sort_all"
    bl_label = "Sort All Trees"
    bl_description = "Sort every node tree in the file: Geometry Nodes, materials, worlds and compositor. Ctrl+Z undoes it"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        """Sort all trees; trees that would change logic are left as they were."""
        ed = Editor(context.area)
        cfg = config(context)
        done, failed = 0, []
        try:
            for nt in api.all_trees():
                try:
                    api.format_tree(nt, context.window_manager.nodefmt_mode, ed, cfg=cfg)
                    done += 1
                except api.LogicChanged as e:
                    failed.append(str(e))
        finally:
            ed.close()
        for f in failed:
            self.report({'WARNING'}, f)
        self.report({'INFO'}, f"Sorted {done} trees, {len(failed)} left unchanged")
        return {'FINISHED'}


class NODEFMT_OT_check(bpy.types.Operator):
    """Check the tree shown in the editor: the rules it breaks, by code; changes nothing."""
    bl_idname = "node.nodefmt_check"
    bl_label = "Check Current Tree"
    bl_description = "Report the rules this tree breaks, without changing it. Results appear below"

    @classmethod
    def poll(cls, context):
        """Available in a node editor showing a tree of a supported type."""
        return NODEFMT_OT_sort_tree.poll(context)

    def execute(self, context):
        """Check the edited tree and keep the result for the panel."""
        nt = context.space_data.edit_tree
        ed = Editor(context.area)
        try:
            vs = api.check_tree(nt, context.window_manager.nodefmt_mode, ed, config(context))
        finally:
            ed.close()
        _LAST["tree"] = api.tree_name(nt)
        _LAST["lines"] = lint.report(vs)
        _LAST["done"] = True
        for line in _LAST["lines"]:
            print(line)
        counts = ", ".join(f"{c} x{n}" for c, n in lint.counts(vs).items())
        self.report({'WARNING'} if vs else {'INFO'},
                    f"{api.tree_name(nt)}: {len(vs)} violations ({counts})" if vs else f"{api.tree_name(nt)}: no violations")
        return {'FINISHED'}


class NODEFMT_PT_panel(bpy.types.Panel):
    """Sidebar panel (Node Editor > Sidebar > nodefmt)."""
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "nodefmt"
    bl_label = "nodefmt"

    @classmethod
    def poll(cls, context):
        """Shown for Geometry Nodes, Shader and Compositor trees."""
        return context.space_data.tree_type in api.TREE_TYPES

    def draw(self, context):
        """Buttons, mode, the rule toggles and the last check."""
        col = self.layout.column()
        col.operator(NODEFMT_OT_sort_tree.bl_idname, icon='NODETREE')
        col.operator(NODEFMT_OT_sort_all.bl_idname, icon='FILE_BLEND')
        col.operator(NODEFMT_OT_check.bl_idname, icon='CHECKMARK')
        col.prop(context.window_manager, "nodefmt_mode", text="")
        row = col.row()
        row.label(text=f"UI scale {context.preferences.system.ui_scale:g}")
        row.label(text="(wires are exact at this scale)")
        cfg = config(context)
        if cfg.source:
            col.label(text=f"Rules: {os.path.basename(cfg.source)}", icon='FILE_TEXT')
        p = _prefs(context)
        if p is not None:
            box = col.box()
            box.label(text="Rules")
            box.prop(p, "use_config_file")
            box.prop(p, "thorough")
            sub = box.column(align=True)
            sub.enabled = not cfg.source
            for code in rules.STYLE:
                sub.prop(p, "rule_" + code)
        if _LAST["done"]:
            box = col.box()
            box.label(text=f"Last check: {_LAST['tree']}")
            if not _LAST["lines"]:
                box.label(text="No problems: the tree is sorted", icon='CHECKMARK')
            for line in _LAST["lines"][:12]:
                box.label(text=line)
            if len(_LAST["lines"]) > 12:
                box.label(text=f"... {len(_LAST['lines']) - 12} more (see the console)")


CLASSES = (NODEFMT_AddonPreferences, NODEFMT_OT_sort_tree, NODEFMT_OT_sort_all, NODEFMT_OT_check,
           NODEFMT_PT_panel)


def register():
    """Register the preferences, operators, panel and the mode property."""
    bpy.types.WindowManager.nodefmt_mode = bpy.props.EnumProperty(name="Mode", items=MODES, default='relayout')
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    """Unregister everything register() added."""
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.nodefmt_mode
