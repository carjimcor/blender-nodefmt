# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on: buttons in the Node Editor sidebar (nodefmt tab) and rule toggles in the preferences.

The rules come from a nodefmt.toml next to the .blend file (or in a folder above it) when there
is one and "Use nodefmt.toml" is on, else from the toggles (preferences, also shown in the
panel). The layout is made for the UI scale Blender runs at. Every format is one undo step.
"""
import os
import time

import bpy

from . import api, check, lint, rules
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


class SortJob:
    """Sorts a list of trees one step at a time (api.format_steps), so a modal operator can
    show progress between steps; cancel() puts every tree back as it was."""

    def __init__(self, trees, area, mode, cfg):
        """The trees to sort, the node editor area that draws them, the mode and the rules."""
        self.trees = list(trees)
        self.names = [api.tree_name(nt) for nt in self.trees]
        self.mode, self.cfg = mode, cfg
        self.ed = Editor(area)
        self.i = 0
        self.gen = None
        self.snaps = []      # (tree, check.Snapshot) of every tree started, to cancel
        self.stats, self.failed = [], []
        self.factor = 0.0    # done, 0..1 (never goes back)
        self.tree_factor = 0.0
        self.text = "Starting"

    def step(self):
        """Run one step; False when every tree is done."""
        if self.gen is None:
            if self.i >= len(self.trees):
                return False
            nt = self.trees[self.i]
            self.ed.show(nt)
            self.snaps.append((nt, check.Snapshot(nt)))
            self.gen = api.format_steps(nt, self.mode, self.ed, cfg=self.cfg)
            self.tree_factor = 0.0
        try:
            st = next(self.gen)
        except StopIteration as e:
            self.stats.append(e.value)
            self._next_tree()
        except api.LogicChanged as e:
            self.failed.append(str(e))
            self._next_tree()
        else:
            # two passes is the usual: the second finds nothing to move
            f = (st.npass - 1 + st.step / st.steps) / max(2, st.npass)
            self.tree_factor = min(0.99, max(self.tree_factor, f))
            self.factor = max(self.factor, (self.i + self.tree_factor) / len(self.trees))
            self.text = f"Tree {self.i + 1}/{len(self.trees)} {self.names[self.i]}: {st.text()}"
        return True

    def _next_tree(self):
        """The current tree is done (or failed): go on with the next one."""
        self.gen = None
        self.i += 1
        self.factor = self.i / len(self.trees)

    def run(self):
        """Run every step at once."""
        while self.step():
            pass

    def cancel(self):
        """Stop and put every tree started back as it was, the last one first."""
        if self.gen is not None:
            self.gen.close()
            self.gen = None
        for nt, snap in reversed(self.snaps):
            snap.restore(nt, self.ed)

    def close(self):
        """Put the editor back as it was."""
        self.ed.close()


_JOB = {"job": None}  # the sort in progress, shown in the panel


def _redraw_editors():
    """Redraw every node editor (the panel shows the progress)."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()


class SortModal:
    """A sort that runs in steps with progress (modal, Esc cancels), or at once (execute, for
    scripts). One undo step either way."""
    bl_options = {'REGISTER', 'UNDO'}

    def trees(self, context):
        """The trees to sort."""
        raise NotImplementedError

    def _job(self, context):
        """A SortJob for this operator's trees."""
        return SortJob(self.trees(context), context.area, context.window_manager.nodefmt_mode, config(context))

    def execute(self, context):
        """Sort without returning to Blender in between (no progress shown)."""
        job = self._job(context)
        try:
            job.run()
        finally:
            job.close()
        return self._finish(job)

    def invoke(self, context, event):
        """Start the sort; a timer drives it."""
        if _JOB["job"] is not None:
            self.report({'WARNING'}, "A sort is already running")
            return {'CANCELLED'}
        self.job = _JOB["job"] = self._job(context)
        self.workspace = context.workspace
        wm = context.window_manager
        self.timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        self._show()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Run steps for up to 50 ms per timer tick; Esc cancels. Other events are held back,
        so nothing changes the trees while they are being sorted."""
        job = self.job
        if event.type == 'ESC' and event.value == 'PRESS':
            try:
                job.cancel()
            finally:
                self._end(context)
            self.report({'WARNING'}, "Sort cancelled: the trees are as they were")
            return {'CANCELLED'}
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        t0 = time.perf_counter()
        try:
            while True:
                if not job.step():
                    self._end(context)
                    return self._finish(job)
                if time.perf_counter() - t0 > 0.05:
                    break
        except Exception:
            try:
                job.cancel()
            finally:
                self._end(context)
            raise
        self._show()
        return {'RUNNING_MODAL'}

    def _show(self):
        """The progress in the status bar and the panel."""
        job = self.job
        self.workspace.status_text_set(f"nodefmt: {job.text}  ({job.factor:.0%}, Esc to cancel)")
        _redraw_editors()

    def _end(self, context):
        """Remove the timer, clear the status bar, put the editor back."""
        context.window_manager.event_timer_remove(self.timer)
        self.workspace.status_text_set(None)
        _JOB["job"] = None
        self.job.close()
        _redraw_editors()

    def _finish(self, job):
        """Report the result (one tree: its stats, else a count)."""
        for f in job.failed:
            self.report({'WARNING'} if len(job.trees) > 1 else {'ERROR'}, f)
        if len(job.trees) == 1:
            if not job.stats:
                return {'CANCELLED'}
            st = job.stats[0]
            self.report({'INFO'}, f"Sorted {st['tree']} ({st['reroutes']} reroutes, {st['seconds']} s, "
                                  f"UI scale {st['ui_scale']:g})")
        else:
            self.report({'INFO'}, f"Sorted {len(job.stats)} trees, {len(job.failed)} left unchanged")
        return {'FINISHED'}


class NODEFMT_OT_sort_tree(SortModal, bpy.types.Operator):
    """Sort (format) the tree shown in the node editor."""
    bl_idname = "node.nodefmt_sort_tree"
    bl_label = "Sort Current Tree"
    bl_description = "Sort the node tree in this editor. Esc cancels, Ctrl+Z undoes it"

    @classmethod
    def poll(cls, context):
        """Available in a node editor showing a tree of a supported type, when no sort runs."""
        sp = context.space_data
        return (_JOB["job"] is None and sp and sp.type == 'NODE_EDITOR' and sp.edit_tree
                and api.formattable(sp.edit_tree))

    def trees(self, context):
        """The edited tree."""
        return [context.space_data.edit_tree]


class NODEFMT_OT_sort_all(SortModal, bpy.types.Operator):
    """Sort (format) every node tree of the file (Geometry Nodes, shader, compositor)."""
    bl_idname = "node.nodefmt_sort_all"
    bl_label = "Sort All Trees"
    bl_description = ("Sort every node tree in the file: Geometry Nodes, materials, worlds and compositor. "
                      "Esc cancels, Ctrl+Z undoes it")

    @classmethod
    def poll(cls, context):
        """Available when no sort runs."""
        return _JOB["job"] is None

    def trees(self, context):
        """Every tree of the file that can be sorted."""
        return api.all_trees()


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
        job = _JOB["job"]
        if job is not None:
            box = col.box()
            box.progress(factor=job.factor, type='BAR', text=f"Sorting: {job.factor:.0%}")
            box.label(text=job.text)
            box.label(text="Esc cancels and puts the trees back", icon='CANCEL')
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
