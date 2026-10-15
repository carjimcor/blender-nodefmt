# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshot each rule example before and after sorting (the images of docs/RULES.md).

    blender --factory-startup --python tools/capture_examples.py -- OUT_DIR [--only NF031 ...]
        [--width 600] [--zoom 0.8]

Runs with Blender's window at UI scale 1.0 (or the example's own, see make_examples.py) and
closes itself; the examples are appended, never saved. For each examples/NF0xx.blend it writes
OUT_DIR/NF0xx-before.png and NF0xx-after.png at one zoom (see make_pair), each place that breaks
the rule ringed in red in the before image (NF005: the logic fingerprint under both). It also
writes selection-before.png and selection-after.png (Sort Selection), check-panel.png (the Check
panel) and boxes.json, the part of each screenshot that holds the tree, which
tools/finish_images.py crops to. --only also takes "selection" and "panel".
"""
import argparse
import glob
import json
import math
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="capture_examples.py")
ap.add_argument("out")
ap.add_argument("--only", action="append", default=[])
ap.add_argument("--examples", default=os.path.join(ROOT, "examples"))
ap.add_argument("--width", type=float, default=600.0, help="widest tree in pixels (default 600)")
ap.add_argument("--zoom", type=float, default=0.8, help="largest zoom, pixels per node unit")
ARGS = ap.parse_args(argv)
PAD = 24  # pixels kept around the tree
SCALE_KEY = "nodefmt_ui_scale"  # custom property of an example shown at another UI scale
STAMP = []  # (x, y, text) in node units: a line of text drawn by draw_marks() (NF005)
MARKS = []  # (x, y, text) in node units, drawn by draw_marks()


def area_region():
    """The node editor area of the window and its main region."""
    win = bpy.context.window_manager.windows[0]
    area = next(a for a in win.screen.areas if a.type == 'NODE_EDITOR')
    return win, area, next(r for r in area.regions if r.type == 'WINDOW')


def draw_marks():
    """Ring each mark in red and write its text next to it."""
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
    if STAMP:
        x, y, text = STAMP[0]
        ui = bpy.context.preferences.system.ui_scale
        cx, cy = bpy.context.region.view2d.view_to_region(x * ui, y * ui, clip=False)
        blf.size(0, 14)
        blf.color(0, 0.85, 0.85, 0.85, 1.0)
        blf.position(0, cx, cy, 0)
        blf.draw(0, text)
    if not MARKS:
        return
    region = bpy.context.region
    v2d = region.view2d
    ui = bpy.context.preferences.system.ui_scale
    shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    shader.uniform_float("viewportSize", (region.width, region.height))
    shader.uniform_float("lineWidth", 2.0)
    shader.uniform_float("color", (1.0, 0.25, 0.2, 1.0))
    gpu.state.blend_set('ALPHA')
    done = []
    for x, y, text in MARKS:
        cx, cy = v2d.view_to_region(x * ui, y * ui, clip=False)
        r = 13.0
        pts = [(cx + r * math.cos(k * math.pi / 16), cy + r * math.sin(k * math.pi / 16)) for k in range(33)]
        batch_for_shader(shader, 'LINE_STRIP', {"pos": pts}).draw(shader)
        if any(abs(cx - a) < 60 and abs(cy - b) < 30 for a, b in done):
            continue  # one text for marks close together
        done.append((cx, cy))
        blf.size(0, 13)
        blf.color(0, 1.0, 0.35, 0.3, 1.0)
        blf.position(0, cx + r + 3, cy + r - 4, 0)
        blf.draw(0, text)
    gpu.state.blend_set('NONE')


def append(path):
    """The node group of an example file, appended (a fresh copy every time)."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
    return dst.node_groups[0]


def bbox(nt):
    """(left, bottom, right, top) of a drawn tree in node units, y up (frames included)."""
    ui = bpy.context.preferences.system.ui_scale
    xs, ys = [], []
    for n in nt.nodes:
        x, y = n.location_absolute
        w, h = (n.dimensions.x / ui, n.dimensions.y / ui) if n.bl_idname != 'NodeReroute' else (0, 0)
        xs += [x - 6, x + w + 6]
        ys += [y - h - 6, y + 6]
    return min(xs), min(ys), max(xs), max(ys)


def fit(nt, cx, cy, zoom):
    """Zoom the editor to `zoom` pixels per node unit around (cx, cy): frame two temporary
    reroutes, measure the zoom Blender settles on, and try again until it matches."""
    win, area, region = area_region()
    half_w, half_h = region.width / zoom / 2, region.height / zoom / 2
    for _ in range(5):
        corners = [nt.nodes.new('NodeReroute') for _ in range(2)]
        corners[0].location_absolute = (cx - half_w, cy - half_h)
        corners[1].location_absolute = (cx + half_w, cy + half_h)
        yield 0.3
        for n in nt.nodes:
            n.select = n in corners
        win, area, region = area_region()
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.node.view_selected()
        yield 0.3
        for n in corners:
            nt.nodes.remove(n)
        v = area_region()[2].view2d
        ui = bpy.context.preferences.system.ui_scale
        got = (v.view_to_region(100 * ui, 0, clip=False)[0] - v.view_to_region(0, 0, clip=False)[0]) / 100
        if abs(got / zoom - 1) < 0.005:
            break
        half_w *= got / zoom
        half_h *= got / zoom
    yield 0.3


def shoot(nt, path, zoom, selected=()):
    """Screenshot the tree at `zoom`, with the nodes `selected` selected; returns the crop box
    (pixels from the top left)."""
    l, b, r, t = bbox(nt)
    yield from fit(nt, (l + r) / 2, (b + t) / 2, zoom)
    for n in nt.nodes:
        n.select = n.name in selected
    yield 0.3
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=path)
    yield 0.3
    ui = bpy.context.preferences.system.ui_scale
    v = region.view2d
    x0, y0 = v.view_to_region(l * ui, t * ui, clip=False)
    x1, y1 = v.view_to_region(r * ui, b * ui, clip=False)
    ox, oy = region.x - area.x, region.y - area.y
    H = area.height
    return [math.floor(x0 + ox - PAD), math.floor(H - (y0 + oy) - PAD),
            math.ceil(x1 + ox + PAD), math.ceil(H - (y1 + oy) + PAD)]


PANEL = ("NF032", "NF032")  # the example of the Check panel image, and the rule clicked in it


def shoot_panel(path):
    """Screenshot the sidebar with the result of Check on an example (one rule clicked) and the
    marks in the editor: check-panel.png. The add-on is registered from this folder and the
    other tabs of the sidebar are removed (in memory only), so the nodefmt tab shows."""
    from nodefmt import ui
    from nodefmt.draw import Editor
    ui.register()
    for c in list(bpy.types.Panel.__subclasses__()):
        if getattr(c, "bl_space_type", "") == 'NODE_EDITOR' and getattr(c, "bl_region_type", "") == 'UI' \
                and getattr(c, "bl_category", "") != "nodefmt" and not getattr(c, "bl_parent_id", ""):
            try:
                bpy.utils.unregister_class(c)
            except RuntimeError:
                pass
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area(use_hide_panels=True)  # back from the full screen ...
    yield 1.0
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area(use_hide_panels=False)  # ... to a maximized editor with its sidebar
    yield 1.0
    nt = append(path)
    nt.use_fake_user = True
    ed = Editor(area_region()[1])
    ed.show(nt)
    win, area, region = area_region()
    sp = area.spaces.active
    sp.show_region_ui = True
    sp.show_region_header = False
    sp.show_region_toolbar = False
    sp.overlay.show_context_path = False
    yield 1.0
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.node.nodefmt_check()
        bpy.ops.node.nodefmt_show_violation(code=PANEL[1])
    chosen = {n.name for n in nt.nodes if n.select}
    side = next(r for r in area.regions if r.type == 'UI')
    l, b, r, t = bbox(nt)
    zoom = 0.8
    overlap = region.width >= area.width - 2  # the sidebar is drawn over the editor
    # the tree's top right corner 60 pixels from the top and 40 from the sidebar
    right = region.width - (side.width if overlap else 0) - 40
    cx = r - (right - region.width / 2) / zoom
    cy = t - (region.height - 60 - region.height / 2) / zoom
    yield from fit(nt, cx, cy, zoom)
    for n in nt.nodes:
        n.select = n.name in chosen
    yield 0.5
    out = os.path.join(ARGS.out, "check-panel.png")
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screenshot_area(filepath=out)
    yield 0.3
    v = region.view2d
    ui_s = bpy.context.preferences.system.ui_scale
    x0, _y0 = v.view_to_region(l * ui_s, t * ui_s, clip=False)
    _x1, y1 = v.view_to_region(r * ui_s, b * ui_s, clip=False)
    ox, oy, H = region.x - area.x, region.y - area.y, area.height
    bottom = max(H - (y1 + oy) + PAD, 460)
    box = [math.floor(x0 + ox - PAD), 0, area.width, math.ceil(bottom)]
    ed.close()
    return box


def fingerprint_digest(nt):
    """The first 12 hex digits of a hash of the tree's logic fingerprint (check.fingerprint)."""
    import hashlib

    from nodefmt import check
    text = json.dumps(check.fingerprint(nt), sort_keys=True, default=repr)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def make_pair(code, before, after, ed):
    """Sort the two copies of example `code` for its images: a guarantee is shown as it is and
    after a sort with no style rules; a style rule after a sort with every style rule off and
    after a sort with only that rule. Returns the violations of the rule in the before tree."""
    from nodefmt import api, rules
    guarantees = frozenset(rules.GUARANTEES)
    if code in rules.STYLE:
        api.format_tree(before, 'relayout', ed, cfg=rules.Config(guarantees))
        api.format_tree(after, 'relayout', ed, cfg=rules.Config(guarantees | {code}))
    else:
        api.format_tree(after, 'relayout', ed, cfg=rules.Config(guarantees))
    ed.show(before)
    own = rules.Config(guarantees | {code})
    return api.check_tree(before, 'relayout', ed, own, formatted=False)


def run():
    """Capture every example (a generator: the timer waits between steps)."""
    from nodefmt.draw import Editor
    bpy.context.preferences.view.ui_scale = 1.0  # in memory only
    bpy.context.preferences.view.smooth_view = 0
    win = bpy.context.window_manager.windows[0]
    big = max(win.screen.areas, key=lambda a: a.width * a.height)
    big.ui_type = 'GeometryNodeTree'
    yield 0.5
    win, area, region = area_region()
    with bpy.context.temp_override(window=win, area=area, region=region):
        bpy.ops.screen.screen_full_area(use_hide_panels=True)
    yield 1.0
    win, area, region = area_region()
    sp = area.spaces.active
    sp.show_region_header = False
    sp.show_region_toolbar = False
    sp.show_region_ui = False
    sp.overlay.show_context_path = False
    handle = bpy.types.SpaceNodeEditor.draw_handler_add(draw_marks, (), 'WINDOW', 'POST_PIXEL')
    os.makedirs(ARGS.out, exist_ok=True)
    boxes = {}
    files = sorted(glob.glob(os.path.join(ARGS.examples, "NF*.blend")))
    try:
        for path in files:
            name = os.path.splitext(os.path.basename(path))[0]
            code = name.split("-")[0]  # NF0xx-<what>: a second example of rule NF0xx
            if ARGS.only and name not in ARGS.only:
                continue
            before, after = append(path), append(path)
            scale = before.get(SCALE_KEY, 1.0)
            if bpy.context.preferences.view.ui_scale != scale:
                bpy.context.preferences.view.ui_scale = scale  # in memory only
                yield 1.0
            ed = Editor(area_region()[1])
            vs = make_pair(code, before, after, ed)
            ed.show(after)
            wa = bbox(after)
            ed.show(before)
            wb = bbox(before)
            width = max(wb[2] - wb[0], wa[2] - wa[0])
            zoom = min(ARGS.zoom, ARGS.width / width)
            MARKS[:] = [(v.x, v.y, v.code) for v in vs if v.code == code and (v.x, v.y) != (0.0, 0.0)]
            for nt, when in ((before, "before"), (after, "after")):
                ed.show(nt)
                if code == "NF005":  # the logic fingerprint under the tree
                    l, b, _r, _t = bbox(nt)
                    STAMP[:] = [(l, b - 20 / zoom, f"Logic fingerprint: {fingerprint_digest(nt)}")]
                box = yield from shoot(nt, os.path.join(ARGS.out, f"{name}-{when}.png"), zoom)
                if STAMP:
                    box[3] += 28
                boxes[f"{name}-{when}"] = box
                MARKS[:] = []
                STAMP[:] = []
            bpy.data.node_groups.remove(before)
            bpy.data.node_groups.remove(after)
            print(f"captured {name} at zoom {zoom:.2f}", flush=True)
        if bpy.context.preferences.view.ui_scale != 1.0:
            bpy.context.preferences.view.ui_scale = 1.0
            yield 1.0
        sel = os.path.join(ARGS.examples, "selection.blend")
        if os.path.exists(sel) and (not ARGS.only or "selection" in ARGS.only):
            from nodefmt import part
            ed = Editor(area_region()[1])
            before, after = append(sel), append(sel)
            chosen = {n.name for n in before.nodes if n.select}
            ed.show(after)
            part.sort_selection(after, ed)
            ed.show(after)
            kept = {n.name for n in after.nodes if n.select}
            wa = bbox(after)
            ed.show(before)
            wb = bbox(before)
            zoom = min(ARGS.zoom, 1.5 * ARGS.width / max(wb[2] - wb[0], wa[2] - wa[0]))  # a wider tree
            boxes["selection-before"] = yield from shoot(before, os.path.join(ARGS.out, "selection-before.png"),
                                                         zoom, chosen)
            ed.show(after)
            boxes["selection-after"] = yield from shoot(after, os.path.join(ARGS.out, "selection-after.png"),
                                                        zoom, kept)
            print(f"captured selection at zoom {zoom:.2f}", flush=True)
        panel = os.path.join(ARGS.examples, PANEL[0] + ".blend")
        if os.path.exists(panel) and (not ARGS.only or "panel" in ARGS.only):
            boxes["check-panel"] = yield from shoot_panel(panel)
            print("captured the Check panel", flush=True)
    finally:
        bpy.types.SpaceNodeEditor.draw_handler_remove(handle, 'WINDOW')
    with open(os.path.join(ARGS.out, "boxes.json"), "w", encoding="utf-8") as fh:
        json.dump(boxes, fh, indent=1)
    print("done", flush=True)


GEN = run()


def tick():
    """Advance the capture; quit at the end or on an error."""
    try:
        return next(GEN)
    except StopIteration:
        code = 0
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=1.0)
