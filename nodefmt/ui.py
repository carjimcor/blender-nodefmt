# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on UI: the nodefmt tab of the Node Editor sidebar (sort buttons, Check with a list by rule
and marks in the editor, Capture Tree) and the rule toggles in the preferences.

The rules come from a nodefmt.toml next to the .blend file (or in a folder above it) when there
is one and "Use nodefmt.toml" is on, else from the toggles (also shown in the panel). The layout
is made for the UI scale Blender runs at. Every sort is one undo step.
"""
import math
import os
import time
import traceback

import bpy

from . import api, capture, check, lint, rules
from .draw import Editor

MODES = [('relayout', "Relayout", "Build a new layout from scratch: columns, order and wires"),
         ('keep', "Keep layout (experimental)", "Keep your columns and order; only straighten wires and fix reroutes")]
# the last check, for the panel and the overlay: the tree (name, pointer, _tree_key), the
# violations and their points, the occurrence shown last per rule and overall
_LAST = {"done": False, "tree": "", "ptr": 0, "key": None, "violations": [], "points": [], "index": {},
         "shown": None}


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
    on = [c for c in rules.STYLE if getattr(p, "rule_" + c, c not in rules.OPT_IN)]
    enabled = rules.resolve(on, []) if on else rules.resolve(None, ["ALL"])
    return rules.Config(enabled)


def _rule_props():
    """A BoolProperty per style rule for the preferences."""
    props = {}
    for code in rules.STYLE:
        props["rule_" + code] = bpy.props.BoolProperty(
            name=f"{code} {rules.NAMES[code]}", description=rules.SHORT[code],
            default=code not in rules.OPT_IN)
    return props


class NODEFMT_AddonPreferences(bpy.types.AddonPreferences):
    """Rule toggles and options (Preferences > Add-ons > nodefmt)."""
    bl_idname = __package__
    __annotations__ = {
        **_rule_props(),
        "use_config_file": bpy.props.BoolProperty(
            name="Use nodefmt.toml", default=True,
            description="Use the rules in a nodefmt.toml next to the .blend file, if there is one"),
    }

    def draw(self, context):
        """The options and one checkbox per style rule (guarantees are always on)."""
        col = self.layout.column()
        col.prop(self, "use_config_file")
        col.label(text="Style rules (guarantees NF001-NF005 are always on):")
        for code in rules.STYLE:
            col.prop(self, "rule_" + code)


class SortJob:
    """Sorts a list of trees one step at a time (api.format_steps), so a modal operator can show
    progress; cancel() puts every tree back as it was."""

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
        self.t0 = time.perf_counter()
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
            # progress assumes two passes, the usual (the second finds nothing to move)
            f = (st.npass - 1 + st.step / st.steps) / max(2, st.npass)
            self.tree_factor = min(0.99, max(self.tree_factor, f))
            self.factor = max(self.factor, (self.i + self.tree_factor) / len(self.trees))
            self.text = f"Tree {self.i + 1}/{len(self.trees)} {self.names[self.i]}: {st.text()}"
        return True

    def elapsed(self):
        """Time since the sort started, as '42 s' or '3 min 05 s'."""
        s = int(time.perf_counter() - self.t0)
        return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"

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
_CAPTURE = {"job": None, "state": None}  # the capture in progress and how it ended


def _redraw_editors():
    """Redraw every node editor (the panel shows the progress)."""
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type == 'NODE_EDITOR':
                area.tag_redraw()


class SortModal:
    """Mixin for the sort operators: runs in steps with progress (modal, Esc cancels), or at
    once (execute, for scripts). One undo step either way."""
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
        self.workspace.status_text_set(
            f"nodefmt: {job.text}  ({job.factor:.0%}, {job.elapsed()}, Esc to cancel)")
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
        return (_JOB["job"] is None and _CAPTURE["job"] is None and sp and sp.type == 'NODE_EDITOR'
                and sp.edit_tree
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
        """Available when no sort or capture runs."""
        return _JOB["job"] is None and _CAPTURE["job"] is None

    def trees(self, context):
        """Every tree of the file that can be sorted."""
        return api.all_trees()


class NODEFMT_OT_sort_selection(bpy.types.Operator):
    """Sort the selected nodes and reroutes, or the contents of a selected frame (part.py)."""
    bl_idname = "node.nodefmt_sort_selection"
    bl_label = "Sort Selection"
    bl_description = ("Sort only the selected nodes and reroutes, or what is inside a selected frame; the rest "
                      "stays where it is. Ctrl+Z undoes it")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        """Available in a supported node editor with something selected, when no sort runs."""
        return NODEFMT_OT_sort_tree.poll(context) and any(n.select for n in context.space_data.edit_tree.nodes)

    def execute(self, context):
        """Sort the selected part of the edited tree; on a logic change it is restored."""
        from . import part
        nt = context.space_data.edit_tree
        ed = Editor(context.area)
        try:
            st = part.sort_selection(nt, ed, config(context), context.window_manager.nodefmt_mode)
        except part.EmptySelection as e:
            self.report({'WARNING'}, f"Nothing to sort: {e}")
            return {'CANCELLED'}
        except api.LogicChanged as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        finally:
            ed.close()
        moved = " (moved to clear the nodes around it)" if any(st["moved"]) else ""
        self.report({'INFO'}, f"Sorted {st['nodes']} nodes of {st['tree']}{moved}")
        return {'FINISHED'}


SCOPES = [('TREE', "Whole Tree", "Capture every node of the tree"),
          ('SELECTION', "Selection", "Capture the selected nodes, or a selected frame and everything in it")]


class NODEFMT_CaptureSettings(bpy.types.PropertyGroup):
    """The options of Capture Tree (WindowManager.nodefmt_capture)."""
    zoom: bpy.props.FloatProperty(
        name="Zoom", default=1.0, min=0.1, max=4.0, soft_max=3.0, precision=2, step=10,
        description="Screen pixels per node unit (1: node text as Blender draws it at UI scale 1)")
    scope: bpy.props.EnumProperty(name="Capture", items=SCOPES, default='TREE')
    margin: bpy.props.IntProperty(
        name="Margin", default=40, min=0, max=2000, subtype='PIXEL',
        description="Empty space around the tree, in pixels")
    hide_overlays: bpy.props.BoolProperty(
        name="Hide Overlays", default=True,
        description="Hide what is not part of the tree: the context path, gizmos and the marks of Check")
    filepath: bpy.props.StringProperty(
        name="File", subtype='FILE_PATH', default="",
        description="The PNG file, or a folder for '<tree name>.png'. Empty: a 'captures' folder next to "
                    "the .blend file (the temporary folder if the file is not saved)")
    clipboard: bpy.props.BoolProperty(
        name="Copy to Clipboard", default=False, description="Also copy the image to the clipboard")
    open_image: bpy.props.BoolProperty(
        name="Open in Image Editor", default=False,
        description="Show the image in an Image Editor of this window, or in a new window")


class NODEFMT_OT_capture_tree(bpy.types.Operator):
    """Save an image of the whole tree shown in the node editor, at a chosen zoom (capture.py).

    The steps run in an application timer, not in the operator's event handler: the capture
    maximises the editor and puts it back, and Blender must not change the screen while it is
    going through event handlers. The modal operator holds back other input, takes Esc and
    reports the result."""
    bl_idname = "node.nodefmt_capture_tree"
    bl_label = "Capture Tree"
    bl_description = ("Save an image of the tree in this editor at the zoom set below, larger than the "
                      "screen if needed. The tree does not change. Esc cancels")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        """Available in a node editor showing a tree, when no sort or capture runs."""
        sp = context.space_data
        return (_JOB["job"] is None and _CAPTURE["job"] is None and sp is not None
                and sp.type == 'NODE_EDITOR' and sp.edit_tree is not None and context.area is not None)

    def _job(self, context):
        """A CaptureJob for the editor, with the panel's options."""
        opt = capture.Options.from_settings(context.window_manager.nodefmt_capture)
        return capture.CaptureJob(context.window, context.area, opt)

    def execute(self, context):
        """Capture at once, in the editor as it is, not maximised (for scripts, which may run
        inside an event handler; no progress shown)."""
        try:
            job = self._job(context)
            job.opt.maximise = False
            job.run()
        except capture.CaptureError as e:
            self.report({'ERROR'}, f"Capture Tree: {e}")
            return {'CANCELLED'}
        return self._finish(job)

    def invoke(self, context, event):
        """Start the capture: a timer runs its steps, the modal handler waits for the end."""
        try:
            self.job = self._job(context)
        except capture.CaptureError as e:
            self.report({'ERROR'}, f"Capture Tree: {e}")
            return {'CANCELLED'}
        _CAPTURE.update(job=self.job, state=None, error=None, stop=False, workspace=context.workspace)
        wm = context.window_manager
        self.timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        _capture_status()
        bpy.app.timers.register(_capture_tick, first_interval=0.01)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        """Esc asks the timer to stop; the end is reported once the timer is done. Other events
        are held back, so nothing changes the editor while it is being captured."""
        if event.type == 'ESC' and event.value == 'PRESS':
            _CAPTURE["stop"] = True
            return {'RUNNING_MODAL'}
        if event.type != 'TIMER' or _CAPTURE["state"] is None:
            return {'RUNNING_MODAL'}
        state, error = _CAPTURE["state"], _CAPTURE["error"]
        context.window_manager.event_timer_remove(self.timer)
        _CAPTURE.update(job=None, state=None, error=None, stop=False, workspace=None)
        _redraw_editors()
        if state == 'done':
            return self._finish(self.job)
        if state == 'cancelled':
            self.report({'WARNING'}, "Capture cancelled: the editor is as it was")
        else:
            self.report({'ERROR'}, f"Capture Tree: {error}")
        return {'CANCELLED'}

    def _finish(self, job):
        """Report the file, its size and any warning."""
        for w in job.warnings:
            self.report({'WARNING'}, f"Capture Tree: {w}")
        self.report({'INFO'}, job.report())
        return {'FINISHED'}


def _capture_status(clear=False):
    """The progress of the capture in the status bar, or clear it."""
    ws, job = _CAPTURE.get("workspace"), _CAPTURE.get("job")
    if ws is None or job is None:
        return
    text = None if clear else f"nodefmt: Capture {job.text}  ({job.factor:.0%}, {job.elapsed()}, Esc to cancel)"
    try:
        ws.status_text_set(text)
    except ReferenceError:
        pass


def _capture_tick():
    """Run steps of the capture for up to 50 ms (an application timer); on the end, Esc or an
    error, put the editor back and leave the result for the operator."""
    job = _CAPTURE.get("job")
    if job is None or _CAPTURE.get("state") is not None:
        return None
    t0 = time.perf_counter()
    try:
        if _CAPTURE.get("stop"):
            job.cancel()
            _CAPTURE["state"] = 'cancelled'
        else:
            while True:
                if not job.step():
                    job.close()
                    _CAPTURE["state"] = 'done'
                    break
                if time.perf_counter() - t0 > 0.05:
                    break
    except Exception as e:
        if not isinstance(e, capture.CaptureError):
            traceback.print_exc()
        try:
            job.cancel()
        except Exception:
            traceback.print_exc()
        _CAPTURE.update(state='error', error=e)
    if _CAPTURE["state"] is not None:
        _capture_status(clear=True)
        return None
    _capture_status()
    return 0.0


def _tree_key(nt):
    """A cheap fingerprint of where everything is, to tell when a tree changed after a check."""
    return (len(nt.nodes), len(nt.links),
            round(sum(n.location_absolute.x + n.location_absolute.y for n in nt.nodes), 1))


def _point(nt, v):
    """Where violation v is (node units, y up): its point, else the middle of its nodes."""
    if (v.x, v.y) != (0.0, 0.0) or not v.nodes:
        return v.x, v.y
    ui = bpy.context.preferences.system.ui_scale
    pts = []
    for k in v.nodes:
        n = nt.nodes.get(k)
        if n is not None:
            x, y = n.location_absolute
            pts.append((x + n.dimensions.x / ui / 2, y - n.dimensions.y / ui / 2))
    if not pts:
        return v.x, v.y
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def checked(context):
    """The result of the last check if it is about the tree in this editor and the tree did not
    change since, else None."""
    sp = context.space_data
    nt = getattr(sp, "edit_tree", None)
    if not _LAST["done"] or nt is None or nt.as_pointer() != _LAST["ptr"]:
        return None
    if _tree_key(nt) != _LAST["key"]:
        return None
    return _LAST


class NODEFMT_OT_check(bpy.types.Operator):
    """Check the tree shown in the editor: the rules it breaks, by code; changes nothing."""
    bl_idname = "node.nodefmt_check"
    bl_label = "Check Current Tree"
    bl_description = ("Find the rules this tree breaks, without changing it. The panel lists them by rule; "
                      "click one to select and frame its places")

    @classmethod
    def poll(cls, context):
        """Available in a node editor showing a tree of a supported type."""
        return NODEFMT_OT_sort_tree.poll(context)

    def execute(self, context):
        """Check the edited tree and keep the result for the panel and the overlay."""
        nt = context.space_data.edit_tree
        ed = Editor(context.area)
        try:
            vs = api.check_tree(nt, context.window_manager.nodefmt_mode, ed, config(context))
        finally:
            ed.close()
        _LAST.update(done=True, tree=api.tree_name(nt), ptr=nt.as_pointer(), key=_tree_key(nt),
                     violations=vs, points=[_point(nt, v) for v in vs], index={}, shown=None)
        for line in lint.report(vs):
            print(line)
        counts = ", ".join(f"{c} x{n}" for c, n in lint.counts(vs).items())
        self.report({'WARNING'} if vs else {'INFO'},
                    f"{api.tree_name(nt)}: {len(vs)} violations ({counts})" if vs
                    else f"{api.tree_name(nt)}: no problems, the tree is sorted")
        _redraw_editors()
        return {'FINISHED'}


class NODEFMT_OT_show_violation(bpy.types.Operator):
    """Select the nodes and reroutes of the next place that breaks a rule, and frame them."""
    bl_idname = "node.nodefmt_show_violation"
    bl_label = "Show Violation"
    bl_description = ("Select the next place that breaks this rule and frame it in the editor "
                      "(click again for the next one)")

    code: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        """Available while the last check is about the tree in this editor."""
        return checked(context) is not None

    def execute(self, context):
        """Select the next occurrence of the rule and View Selected."""
        nt = context.space_data.edit_tree
        found = [k for k, v in enumerate(_LAST["violations"]) if v.code == self.code]
        if not found:
            return {'CANCELLED'}
        k = (_LAST["index"].get(self.code, -1) + 1) % len(found)
        _LAST["index"][self.code] = k
        _LAST["shown"] = found[k]
        v = _LAST["violations"][found[k]]
        x, y = _LAST["points"][found[k]]
        names = {n for n in v.nodes if n in nt.nodes}
        for n in nt.nodes:  # the reroutes at the place
            if n.bl_idname == 'NodeReroute' and abs(n.location_absolute.x - x) + abs(n.location_absolute.y - y) < 16:
                names.add(n.name)
        for n in nt.nodes:
            n.select = n.name in names
        temp = None
        if not names:  # nothing to select: frame the place itself
            temp = nt.nodes.new('NodeReroute')
            temp.location_absolute = (x, y)
            temp.select = True
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is not None:
            with context.temp_override(region=region):
                bpy.ops.node.view_selected()
        if temp is not None:
            nt.nodes.remove(temp)
        self.report({'INFO'}, f"{v.code} {k + 1}/{len(found)}: {v.msg}")
        _redraw_editors()
        return {'FINISHED'}


def _draw_overlay():
    """Mark each place of the last check in the node editor with a ring and its rule code (the
    one shown last a bigger ring)."""
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    context = bpy.context
    if not getattr(context.window_manager, "nodefmt_overlay", False):
        return
    res = checked(context)
    if res is None or not res["violations"]:
        return
    region = context.region
    v2d = region.view2d
    ui = context.preferences.system.ui_scale
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.uniform_float("viewportSize", (region.width, region.height))
    gpu.state.blend_set('ALPHA')
    blf.size(0, 12 * ui)
    seen = []
    for k, (v, (x, y)) in enumerate(zip(res["violations"], res["points"])):
        bad = v.code in rules.GUARANTEES or v.code == 'NF900'
        color = (1.0, 0.3, 0.25, 0.95) if bad else (1.0, 0.7, 0.2, 0.95)
        cx, cy = v2d.view_to_region(x * ui, y * ui, clip=False)
        if not (-50 < cx < region.width + 50 and -50 < cy < region.height + 50):
            continue
        r = (16.0 if k == res["shown"] else 11.0) * ui
        pts = [(cx + r * math.cos(t * math.pi / 16), cy + r * math.sin(t * math.pi / 16)) for t in range(33)]
        shader.uniform_float("lineWidth", 3.0 if k == res["shown"] else 2.0)
        shader.uniform_float("color", color)
        batch_for_shader(shader, 'LINE_STRIP', {"pos": pts}).draw(shader)
        if any(abs(cx - a) < 50 * ui and abs(cy - b) < 14 * ui for a, b in seen):
            continue  # one code for marks close together
        seen.append((cx, cy))
        blf.color(0, *color)
        blf.position(0, cx + r + 3, cy - 4 * ui, 0)
        blf.draw(0, v.code)
    gpu.state.blend_set('NONE')


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
        """The progress of a running sort, the buttons, the mode and the UI scale."""
        col = self.layout.column()
        job = _JOB["job"]
        if job is not None:
            box = col.box()
            box.progress(factor=job.factor, type='BAR', text=f"Sorting: {job.factor:.0%}, {job.elapsed()}")
            box.label(text=job.text)
            box.label(text="Esc cancels and puts the trees back", icon='CANCEL')
        col.operator(NODEFMT_OT_sort_tree.bl_idname, icon='NODETREE')
        col.operator(NODEFMT_OT_sort_selection.bl_idname, icon='RESTRICT_SELECT_OFF')
        col.operator(NODEFMT_OT_sort_all.bl_idname, icon='FILE_BLEND')
        col.operator(NODEFMT_OT_check.bl_idname, icon='VIEWZOOM')
        col.prop(context.window_manager, "nodefmt_mode", text="")
        col.label(text=f"Wires exact at UI scale {context.preferences.system.ui_scale:g}")
        cfg = config(context)
        if cfg.source:
            col.label(text=f"Rules: {os.path.basename(cfg.source)}", icon='FILE_TEXT')


class NODEFMT_PT_check(bpy.types.Panel):
    """The result of the last check, grouped by rule (a sub-panel of nodefmt)."""
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "nodefmt"
    bl_label = "Check"
    bl_parent_id = "NODEFMT_PT_panel"

    def draw_header(self, context):
        """The overlay toggle."""
        self.layout.prop(context.window_manager, "nodefmt_overlay", text="", icon='OVERLAY')

    def draw(self, context):
        """One row per rule broken: icon, code and name (click: select and frame the next place),
        and how many places; or 'No problems'."""
        col = self.layout.column()
        if not _LAST["done"]:
            col.label(text="Press Check Current Tree")
            return
        res = checked(context)
        if res is None:
            col.label(text=f"Last check: {_LAST['tree']}")
            col.label(text="The tree changed, or this is another tree:", icon='INFO')
            col.label(text="check again")
            return
        vs = res["violations"]
        if not vs:
            col.label(text="No problems: the tree is sorted", icon='CHECKMARK')
            return
        counts = lint.counts(vs)
        if 'NF900' not in counts and not any(c in rules.GUARANTEES for c in counts):
            col.label(text="Sorted; these style rules could not be met:", icon='CHECKMARK')
        elif 'NF900' in counts:
            col.label(text="Not sorted: Sort Current Tree fixes it", icon='ERROR')
        shown = res["violations"][res["shown"]] if res["shown"] is not None else None
        for code, n in counts.items():
            bad = code in rules.GUARANTEES or code == 'NF900'
            row = col.split(factor=0.86, align=True)
            name = rules.NAMES.get(code, "not-formatted")
            op = row.operator(NODEFMT_OT_show_violation.bl_idname, text=f"{code} {name}",
                              icon='ERROR' if bad else 'INFO', depress=shown is not None and shown.code == code)
            op.code = code
            row.label(text=str(n))
            if shown is not None and shown.code == code:
                k = res["index"].get(code, 0)
                sub = col.column()
                sub.scale_y = 0.8
                for line in _wrap(f"{k + 1}/{n}: {shown.msg}", 44):
                    sub.label(text=line)
        col.separator()
        col.label(text="Click a rule to select its next place", icon='RESTRICT_SELECT_OFF')


def _wrap(text, width):
    """Text split into lines of at most `width` characters, at spaces."""
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    return lines + ([cur] if cur else [])


class NODEFMT_PT_capture(bpy.types.Panel):
    """Capture Tree and its options (a sub-panel of nodefmt)."""
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "nodefmt"
    bl_label = "Capture"
    bl_parent_id = "NODEFMT_PT_panel"

    def draw(self, context):
        """The button, the zoom, what to capture, the margin, the file and the extras."""
        s = context.window_manager.nodefmt_capture
        col = self.layout.column()
        col.operator(NODEFMT_OT_capture_tree.bl_idname, icon='IMAGE_DATA')
        col.prop(s, "zoom")
        col.row().prop(s, "scope", expand=True)
        col.prop(s, "margin")
        col.prop(s, "hide_overlays")
        nt = getattr(context.space_data, "edit_tree", None)
        folder = "//captures" if bpy.data.filepath else "<temp>"
        hint = f"{folder}/{capture.file_name(nt)}.png" if nt is not None else ""
        col.prop(s, "filepath", text="", placeholder=hint)
        col.prop(s, "clipboard")
        col.prop(s, "open_image")


class NODEFMT_PT_rules(bpy.types.Panel):
    """The rule toggles and options (a sub-panel of nodefmt, closed at first)."""
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "nodefmt"
    bl_label = "Rules"
    bl_parent_id = "NODEFMT_PT_panel"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        """Shown when the add-on preferences exist (the add-on is installed)."""
        return _prefs(context) is not None

    def draw(self, context):
        """Use nodefmt.toml and one checkbox per style rule."""
        p = _prefs(context)
        cfg = config(context)
        col = self.layout.column()
        col.prop(p, "use_config_file")
        sub = col.column(align=True)
        sub.enabled = not cfg.source
        for code in rules.STYLE:
            sub.prop(p, "rule_" + code)


CLASSES = (NODEFMT_AddonPreferences, NODEFMT_CaptureSettings, NODEFMT_OT_sort_tree, NODEFMT_OT_sort_selection,
           NODEFMT_OT_sort_all, NODEFMT_OT_check, NODEFMT_OT_show_violation, NODEFMT_OT_capture_tree,
           NODEFMT_PT_panel, NODEFMT_PT_check, NODEFMT_PT_capture, NODEFMT_PT_rules)
_HANDLE = []  # the overlay's draw handler


def register():
    """Register the preferences, operators, panels, the window manager properties (mode, overlay,
    capture options) and the overlay."""
    wm = bpy.types.WindowManager
    wm.nodefmt_mode = bpy.props.EnumProperty(name="Mode", items=MODES, default='relayout')
    wm.nodefmt_overlay = bpy.props.BoolProperty(
        name="Show in Editor", default=True, update=lambda self, context: _redraw_editors(),
        description="Mark each place of the last check in the node editor with its rule code")
    for c in CLASSES:
        bpy.utils.register_class(c)
    wm.nodefmt_capture = bpy.props.PointerProperty(type=NODEFMT_CaptureSettings)
    _HANDLE.append(bpy.types.SpaceNodeEditor.draw_handler_add(_draw_overlay, (), 'WINDOW', 'POST_PIXEL'))


def unregister():
    """Unregister everything register() added."""
    while _HANDLE:
        bpy.types.SpaceNodeEditor.draw_handler_remove(_HANDLE.pop(), 'WINDOW')
    if bpy.app.timers.is_registered(_capture_tick):  # a capture still running: stop it
        bpy.app.timers.unregister(_capture_tick)
        try:
            _CAPTURE["job"].cancel()
        except Exception:
            traceback.print_exc()
    _CAPTURE.update(job=None, state=None)
    del bpy.types.WindowManager.nodefmt_capture
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
    del bpy.types.WindowManager.nodefmt_overlay
    del bpy.types.WindowManager.nodefmt_mode
