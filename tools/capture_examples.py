# SPDX-License-Identifier: GPL-3.0-or-later
"""Screenshot each rule example before and after sorting (the images of docs/RULES.md).

    blender --factory-startup --python tools/capture_examples.py -- OUT_DIR [--only NF031 ...]

Runs with Blender's window at UI scale 1.0 and closes itself; the examples are appended, never
saved. For each examples/NF0xx.blend it writes OUT_DIR/NF0xx-before.png (the tree as it is,
each place that breaks the rule ringed in red with its code) and OUT_DIR/NF0xx-after.png (a
copy sorted with the default rules), both at one zoom, and OUT_DIR/boxes.json with the part of
each screenshot that holds the tree. tools/finish_images.py crops and compresses them.
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


def shoot(nt, path, zoom):
    """Screenshot the tree at `zoom`; returns the crop box (pixels from the top left)."""
    l, b, r, t = bbox(nt)
    yield from fit(nt, (l + r) / 2, (b + t) / 2, zoom)
    for n in nt.nodes:
        n.select = False
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


def run():
    """Capture every example (a generator: the timer waits between steps)."""
    from nodefmt import api, rules
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
            code = os.path.splitext(os.path.basename(path))[0]
            if ARGS.only and code not in ARGS.only:
                continue
            ed = Editor(area_region()[1])
            before, after = append(path), append(path)
            api.format_tree(after, 'relayout', ed)
            vs = api.check_tree(before, 'relayout', ed, formatted=False)
            ed.show(after)
            wa = bbox(after)
            ed.show(before)
            wb = bbox(before)
            width = max(wb[2] - wb[0], wa[2] - wa[0])
            zoom = min(ARGS.zoom, ARGS.width / width)
            MARKS[:] = [(v.x, v.y, v.code) for v in vs if v.code == code and (v.x, v.y) != (0.0, 0.0)]
            ed.show(before)
            boxes[f"{code}-before"] = yield from shoot(before, os.path.join(ARGS.out, f"{code}-before.png"), zoom)
            MARKS[:] = []
            ed.show(after)
            boxes[f"{code}-after"] = yield from shoot(after, os.path.join(ARGS.out, f"{code}-after.png"), zoom)
            bpy.data.node_groups.remove(before)
            bpy.data.node_groups.remove(after)
            print(f"captured {code} at zoom {zoom:.2f}", flush=True)
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
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=1.0)
