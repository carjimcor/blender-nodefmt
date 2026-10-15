# SPDX-License-Identifier: GPL-3.0-or-later
"""Capture Tree: save an image of a whole node tree at a chosen zoom, larger than the screen.

The node editor is maximised, its regions (and optionally the overlays that are not part of the
tree) are hidden, and the view is zoomed to the chosen screen pixels per node unit. The view is
then panned over the tree in whole pixels, one screenshot per tile. Neighbouring tiles overlap,
and a tile is moved a few pixels only if it lines up cleanly there and not where it was planned
(a safety check: pans are exact). The tiles are joined with numpy (no Pillow), cropped to the tree plus a margin and
written as a PNG. Blender dims a wire whose two ends are both far outside the view, except the
wires of selected nodes: while capturing, every node is selected and the theme draws selected
nodes and wires like the others, so long wires keep their colour.

Afterwards the editor is put back as it was (maximised state, regions, overlays, zoom, pan and
selection); the tree is never changed and no undo step is added. A CaptureJob runs in steps so
the add-on can show progress and cancel (ui.py runs them in an application timer: the screen
must not change while Blender goes through event handlers); run() does every step at once.
"""
import math
import os
import struct
import tempfile
import time
import zlib

import bpy
import numpy as np

from . import api

CROP = 40          # pixels dropped from every tile edge (scrollbars, region arrows)
THEME_KEYS = ("node_selected", "node_active", "wire_select")  # theme colours set while capturing
OVERLAP = 96       # pixels shared by neighbouring tiles, to check how they line up
REACH = 4          # how far (pixels) a tile may be moved to line up with the tiles before it
MATCH = 0.002      # share of overlapping pixels that may differ for a tile to count as lined up
EDGE = 8           # node units around every node (outline, shadow, collapsed nodes)
ZONE_EDGE = 30     # node units around every node of a tree with zones (the zone outline)
BADGES = 30        # node units above a Geometry Nodes tree for timing and attribute badges
MAX_PIXELS = 200_000_000  # the largest image: about 800 MB while it is built
REGIONS = ("show_region_header", "show_region_toolbar", "show_region_ui")
OVERLAYS = ("show_context_path",)  # overlays of the editor that are not part of the tree
GIZMOS = ("show_gizmo", "show_gizmo_active_node")


class CaptureError(Exception):
    """The capture cannot be made (nothing to capture, image too large, editor too small)."""
    pass


class Options:
    """What to capture and where to save it (the panel's settings, or the command line's)."""

    def __init__(self, zoom=1.0, selection=False, hide_overlays=True, margin=40, path="",
                 clipboard=False, open_image=False, maximise=True):
        """zoom: screen pixels per node unit; selection: only the selected nodes (and the contents
        of selected frames); margin: pixels around the tree; path: see output_path; maximise:
        maximise the editor first (fewer tiles; only outside event handlers, as in a timer)."""
        self.zoom, self.selection, self.hide_overlays = zoom, selection, hide_overlays
        self.margin, self.path = margin, path
        self.clipboard, self.open_image, self.maximise = clipboard, open_image, maximise

    @classmethod
    def from_settings(cls, s):
        """Options from the panel's settings (a NODEFMT_CaptureSettings)."""
        return cls(s.zoom, s.scope == 'SELECTION', s.hide_overlays, s.margin, s.filepath,
                   s.clipboard, s.open_image)


def file_name(nt):
    """A file name for tree nt: api.tree_name without characters that file systems reject."""
    name = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in api.tree_name(nt))
    return name.strip(" .") or "tree"


def default_folder():
    """Where captures go by default: a 'captures' folder next to the .blend file, or the
    temporary folder if the file is not saved."""
    if bpy.data.filepath:
        return os.path.join(os.path.dirname(bpy.data.filepath), "captures")
    return bpy.context.preferences.filepaths.temporary_directory or tempfile.gettempdir()


def output_path(nt, path=""):
    """The PNG file for a capture of nt: `path` (relative to the .blend with //; a folder gets
    '<tree name>.png'), or by default '<tree name>.png' in default_folder()."""
    if not path:
        return os.path.join(default_folder(), file_name(nt) + ".png")
    p = bpy.path.abspath(path)
    if p.endswith(("/", "\\")) or os.path.isdir(p):
        return os.path.normpath(os.path.join(p, file_name(nt) + ".png"))
    if not p.lower().endswith(".png"):
        p += ".png"
    return os.path.normpath(p)


def tree_bounds(nt, selection=False, badges=False):
    """(left, bottom, right, top) in node units (y up) of what Blender draws of tree nt, or of
    its selected nodes and the contents of selected frames. Needs a drawn tree (dimensions)."""
    ui = bpy.context.preferences.system.ui_scale
    nodes = list(nt.nodes)
    if selection:
        chosen = {n.name for n in nodes if n.select}
        grew = True
        while grew:  # what is inside a selected frame, at any depth
            grew = False
            for n in nodes:
                if n.name not in chosen and n.parent is not None and n.parent.name in chosen:
                    chosen.add(n.name)
                    grew = True
        nodes = [n for n in nodes if n.name in chosen]
        if not nodes:
            raise CaptureError("nothing is selected")
    if not nodes:
        raise CaptureError("the tree is empty")
    zones = any(getattr(n, "paired_output", None) is not None for n in nt.nodes)
    pad = ZONE_EDGE if zones else EDGE
    xs, ys = [], []
    for n in nodes:
        x, y = n.location_absolute
        w, h = n.dimensions.x / ui, n.dimensions.y / ui
        if n.bl_idname == 'NodeReroute':
            x, y, w, h = x - w / 2, y + h / 2, w, h  # a reroute's location is its centre
        xs += [x - pad, x + w + pad]
        ys += [y - h - pad, y + pad]
    return min(xs), min(ys), max(xs), max(ys) + (BADGES if badges else 0)


def png_steps(path, rgb, level=6, rows=64):
    """Write rgb ((height, width, 3) uint8) to `path` as a PNG, a block of rows at a time
    (Paeth filter, zlib); yields the share written. The file appears only when complete."""
    h, w, _ = rgb.shape

    def chunk(tag, data):
        """A PNG chunk: length, tag, data and CRC."""
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    part = path + ".part"
    comp = zlib.compressobj(level)
    try:
        with open(part, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
            prev = np.zeros((1, w * 3), np.int16)
            for y in range(0, h, rows):
                x = rgb[y:y + rows].reshape(-1, w * 3).astype(np.int16)
                b = np.concatenate([prev, x[:-1]])  # the row above
                a = np.zeros_like(x)
                a[:, 3:] = x[:, :-3]                 # the pixel to the left
                c = np.zeros_like(x)
                c[:, 3:] = b[:, :-3]                 # above left
                pa, pb, pc = np.abs(b - c), np.abs(a - c), np.abs(a + b - 2 * c)
                pred = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))
                raw = np.empty((x.shape[0], w * 3 + 1), np.uint8)
                raw[:, 0] = 4                        # filter type: Paeth
                raw[:, 1:] = (x - pred) & 0xFF
                data = comp.compress(raw.tobytes())
                if data:
                    fh.write(chunk(b"IDAT", data))
                prev = x[-1:]
                yield min(1.0, (y + rows) / h)
            fh.write(chunk(b"IDAT", comp.flush()) + chunk(b"IEND", b""))
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)


def png_size(path):
    """(width, height) of a PNG file, from its header."""
    with open(path, "rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def _mismatch(canvas, mask, tile, x, y, rects, step=1):
    """Share of the pixels in `rects` (tile coordinates) that differ from what is already on
    the canvas if the tile's top left sits at (x, y); None if they hardly overlap."""
    H, W = mask.shape
    bad = total = 0
    for r0, r1, c0, c1 in rects:
        ya, yb = max(y + r0, 0), min(y + r1, H)
        xa, xb = max(x + c0, 0), min(x + c1, W)
        if ya >= yb or xa >= xb:
            continue
        m = mask[ya:yb:step, xa:xb:step]
        n = int(m.sum())
        if not n:
            continue
        a = canvas[ya:yb:step, xa:xb:step].astype(np.int16)
        b = tile[ya - y:yb - y:step, xa - x:xb - x:step].astype(np.int16)
        bad += int((np.abs(a - b).sum(axis=2)[m] > 12).sum())
        total += n
    return bad / total if total >= 400 // (step * step) else None


def place(canvas, mask, tile, x, y, rects):
    """Paste `tile` on the canvas at (x, y), or up to REACH pixels away if it lines up cleanly
    only there. A small mismatch alone does not move a tile: Blender dims wires whose ends are
    off view, so the same wire can differ between tiles. Returns (dx, dy, mismatch); mismatch is
    None where the tile overlaps nothing."""
    best = (0, 0, _mismatch(canvas, mask, tile, x, y, rects))
    if best[2] is not None and best[2] > MATCH:
        found = None
        offsets = sorted(((dx, dy) for dx in range(-REACH, REACH + 1) for dy in range(-REACH, REACH + 1)),
                         key=lambda d: abs(d[0]) + abs(d[1]))
        for dx, dy in offsets:  # a coarse look at every offset, nearest first
            m = _mismatch(canvas, mask, tile, x + dx, y + dy, rects, step=2)
            if m is not None and (found is None or m < found[2]):
                found = (dx, dy, m)
        if found is not None and (found[0], found[1]) != (0, 0):
            m = _mismatch(canvas, mask, tile, x + found[0], y + found[1], rects)
            if m is not None and m <= MATCH:  # only a clean match moves a tile
                best = (found[0], found[1], m)
    dx, dy = best[0], best[1]
    H, W = mask.shape
    th, tw = tile.shape[:2]
    ya, yb = max(y + dy, 0), min(y + dy + th, H)
    xa, xb = max(x + dx, 0), min(x + dx + tw, W)
    if ya < yb and xa < xb:
        canvas[ya:yb, xa:xb] = tile[ya - y - dy:yb - y - dy, xa - x - dx:xb - x - dx]
        mask[ya:yb, xa:xb] = True
    return best


def _set_flags(win, items):
    """Set the (object, attribute, value) flags that differ, in window `win` with no area or
    region (as in a timer): inside an area Blender applies a region's visibility late, or toggles it."""
    items = [(obj, k, v) for obj, k, v in items if getattr(obj, k) != v]
    if not items:
        return
    with bpy.context.temp_override(window=win, screen=win.screen, area=None, region=None):
        for obj, k, v in items:
            setattr(obj, k, v)


class CaptureJob:
    """A capture of the tree shown in a node editor, in steps (see the module docstring)."""

    def __init__(self, window, area, options):
        """The window and node editor area that show the tree, and the Options."""
        self.win, self.area = window, area
        self.opt = options
        self.tree = area.spaces.active.edit_tree
        if self.tree is None:
            raise CaptureError("the editor shows no node tree")
        self.name = api.tree_name(self.tree)
        self.path = output_path(self.tree, options.path)
        sp = area.spaces.active
        badges = (self.tree.bl_idname == 'GeometryNodeTree' and sp.overlay.show_overlays
                  and (sp.overlay.show_timing or sp.overlay.show_named_attributes))
        self.bounds = tree_bounds(self.tree, options.selection, badges)
        left, bottom, right, top = self.bounds
        w = math.ceil((right - left) * options.zoom) + 2 * options.margin
        h = math.ceil((top - bottom) * options.zoom) + 2 * options.margin
        if w * h > MAX_PIXELS:
            raise CaptureError(f"the image would be {w} x {h} pixels ({w * h / 1e6:.0f} megapixels, "
                               f"at most {MAX_PIXELS / 1e6:.0f}): lower the zoom")
        self.text, self.factor = "Starting", 0.0
        self.t0 = time.perf_counter()
        self.size = None       # (width, height) of the image
        self.tiles = 0         # how many tiles
        self.matches = []      # (dx, dy, mismatch) of every tile placed
        self.zoom = None       # the zoom reached (pixels per node unit)
        self.warnings = []
        self.saved = None      # the editor state to put back
        self.done = False      # the file is written
        self.image = None      # the image loaded for the clipboard or the Image Editor
        self.copied = False    # the image is on the clipboard
        self.own_image = False  # the image data-block was added by the capture
        self.tmp = None
        self.gen = self._steps()

    # running ---------------------------------------------------------------------------------

    def step(self):
        """Run one step; False when the capture is finished."""
        try:
            next(self.gen)
            return True
        except StopIteration:
            return False

    def run(self):
        """Run every step at once."""
        try:
            while self.step():
                pass
        finally:
            self.close()

    def cancel(self):
        """Stop and put everything back; no file is written."""
        self.gen.close()
        self.close()

    def close(self):
        """Put the editor back (if not done yet) and remove the temporary files."""
        self._restore()
        if self.tmp and os.path.isdir(self.tmp):
            for f in os.listdir(self.tmp):
                os.remove(os.path.join(self.tmp, f))
            os.rmdir(self.tmp)
        self.tmp = None

    def elapsed(self):
        """Time since the capture started, as '4 s' or '1 min 05 s'."""
        s = int(time.perf_counter() - self.t0)
        return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"

    # the editor ------------------------------------------------------------------------------

    def _region(self):
        """The main region of the capture area."""
        return next(r for r in self.area.regions if r.type == 'WINDOW')

    def _override(self):
        """A context override for the capture area."""
        return bpy.context.temp_override(window=self.win, area=self.area, region=self._region())

    def _redraw(self):
        """Draw the window now and show it (swap), so the screenshot reads the current view."""
        with self._override():
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

    def _view(self):
        """(x, y, zoom x, zoom y): where view point (0, 0) is in the region, and region pixels
        per view unit."""
        v = self._region().view2d
        x0, y0 = v.view_to_region(0, 0, clip=False)
        x1, y1 = v.view_to_region(100000, 100000, clip=False)
        return x0, y0, (x1 - x0) / 100000, (y1 - y0) / 100000

    def _set_zoom(self, z):
        """Zoom about the view centre to z region pixels per view unit, both axes alike
        (view2d.zoom takes view units, so it takes a few rounds); stops at Blender's zoom limit."""
        ps = bpy.context.preferences.system.pixel_size
        for _ in range(8):
            r = self._region()
            _, _, cx, cy = self._view()
            if abs(cx / z - 1) < 2e-5:
                return
            f = z / cx
            dx = (r.width / cx - r.width / (cx * f)) / 2 * ps
            dy = (r.height / cy - r.height / (cy * f)) / 2 * ps
            with self._override():
                bpy.ops.view2d.zoom(deltax=dx, deltay=dy)
            if self._view()[2:] == (cx, cy):
                return  # at Blender's zoom limit

    def _pan_to(self, x, y):
        """Pan in whole pixels until view point (0, 0) is at region pixel (x, y) as view_to_region
        reports it (within a pixel or two); True if reached."""
        for _ in range(4):
            cx, cy = self._view()[:2]
            if (cx, cy) == (x, y):
                return True
            with self._override():
                bpy.ops.view2d.pan(deltax=int(cx - x), deltay=int(cy - y))
        return self._view()[:2] == (x, y)

    def _space_state(self, sp):
        """The settings of node editor space sp that a capture changes."""
        state = {"regions": {k: getattr(sp, k) for k in REGIONS if hasattr(sp, k)},
                 "gizmos": {k: getattr(sp, k) for k in GIZMOS if hasattr(sp, k)},
                 "overlay": {k: getattr(sp.overlay, k) for k in OVERLAYS if hasattr(sp.overlay, k)}}
        return state

    def _setup(self):
        """Remember the editor, maximise it, hide regions and overlays, select every node (see the
        module docstring)."""
        wm = bpy.context.window_manager
        screen = self.win.screen
        sp = self.area.spaces.active
        x, y, zx, zy = self._view()
        self.saved = {
            "screen": screen, "index": list(screen.areas).index(self.area),
            "maximised": False, "view": (x, y, zx, zy), "space": self._space_state(sp),
            "marks": getattr(wm, "nodefmt_overlay", None),
            "select": {n.name: n.select for n in self.tree.nodes},
        }
        if self.opt.maximise and not screen.show_fullscreen:
            with self._override():
                bpy.ops.screen.screen_full_area(use_hide_panels=False)
            self.saved["maximised"] = True
            self.area = next(a for a in self.win.screen.areas if a.type == 'NODE_EDITOR')
        sp = self.area.spaces.active
        hide = [(sp, k) for k in self.saved["space"]["regions"]]
        if self.opt.hide_overlays:
            hide += [(sp.overlay, k) for k in self.saved["space"]["overlay"]]
            hide += [(sp, k) for k in self.saved["space"]["gizmos"]]
        _set_flags(self.win, ((obj, k, False) for obj, k in hide))
        if self.opt.hide_overlays and self.saved["marks"]:
            wm.nodefmt_overlay = False
        # Blender dims a wire whose ends are both far outside the view, except the wires of
        # selected nodes: every node is selected, and the theme draws selected nodes and wires
        # like the others while the capture runs
        th = bpy.context.preferences.themes[0].node_editor
        self.saved["theme"] = {k: tuple(getattr(th, k)) for k in THEME_KEYS}
        th.node_selected = th.node_active = tuple(th.wire)[:3]  # the outline of unselected nodes
        th.wire_select = tuple(th.wire_select)[:3] + (0.0,)  # no highlight over the wire's own colour
        for n in self.tree.nodes:
            if not n.select:
                n.select = True
        self._redraw()

    def _restore(self):
        """Put back what _setup changed (once)."""
        s, self.saved = self.saved, None
        if s is None:
            return
        for name, sel in s["select"].items():
            n = self.tree.nodes.get(name)
            if n is not None and n.select != sel:
                n.select = sel
        th = bpy.context.preferences.themes[0].node_editor
        for k, v in s.get("theme", {}).items():
            setattr(th, k, v)
        if s["marks"] is not None:
            bpy.context.window_manager.nodefmt_overlay = s["marks"]
        if s["maximised"] and self.win.screen.show_fullscreen:
            with self._override():
                bpy.ops.screen.screen_full_area(use_hide_panels=False)
        areas = list(s["screen"].areas)
        if s["index"] < len(areas) and areas[s["index"]].type == 'NODE_EDITOR':
            self.area = areas[s["index"]]
        sp = self.area.spaces.active
        _set_flags(self.win, ((obj, k, v) for group, obj in (("regions", sp), ("gizmos", sp), ("overlay", sp.overlay))
                   for k, v in s["space"][group].items()))
        self._redraw()
        x, y, zx, zy = s["view"]
        self._set_zoom(zx)
        self._pan_to(x, y)
        self._redraw()

    # the capture -----------------------------------------------------------------------------

    def _shoot(self):
        """A screenshot of the capture area as (height, width, 3) uint8, top row first."""
        path = os.path.join(self.tmp, "tile.png")
        with self._override():
            bpy.ops.screen.screenshot_area(filepath=path)
        im = bpy.data.images.load(path, check_existing=False)
        try:
            w, h = im.size
            buf = np.empty(w * h * 4, np.float32)
            im.pixels.foreach_get(buf)
        finally:
            bpy.data.images.remove(im)
            os.remove(path)
        return (buf.reshape(h, w, 4)[::-1, :, :3] * 255 + 0.5).astype(np.uint8)

    def _steps(self):
        """The capture, one tile per step, then the restore, the file and the extras."""
        opt = self.opt
        left, bottom, right, top = self.bounds
        self._setup()
        yield
        ui = bpy.context.preferences.system.ui_scale
        z = opt.zoom / ui                       # region pixels per view unit
        self._set_zoom(z)
        zx = self._view()[2]
        self.zoom = zx * ui
        if abs(self.zoom / opt.zoom - 1) > 0.005:
            self.warnings.append(f"zoom {opt.zoom:g} is beyond Blender's limit; used {self.zoom:.2f}")
        m = opt.margin
        bw = math.ceil((right - left) * self.zoom) + 2 * m
        bh = math.ceil((top - bottom) * self.zoom) + 2 * m
        region, area = self._region(), self.area
        ox, oy, ah = region.x - area.x, region.y - area.y, area.height
        uw, uh = region.width - 2 * CROP, region.height - 2 * CROP
        if uw < 2 * OVERLAP or uh < 2 * OVERLAP:
            raise CaptureError("the editor is too small to capture from")
        ux0, uy0 = ox + CROP, ah - oy - region.height + CROP  # the used part of a tile (image pixels)
        sx, sy = uw - OVERLAP, uh - OVERLAP
        nx = 1 if bw <= uw else math.ceil((bw - uw) / sx) + 1
        ny = 1 if bh <= uh else math.ceil((bh - uh) / sy) + 1
        self.size, self.tiles = (bw, bh), nx * ny

        # the tree's top left corner (with the margin) to the top left of the used part
        v = region.view2d
        rx, ry = v.view_to_region(left * ui, top * ui, clip=False)
        with self._override():
            bpy.ops.view2d.pan(deltax=int(ox + rx - m - ux0), deltay=int(uy0 - (ah - oy - ry - m)))
        rx, ry = region.view2d.view_to_region(left * ui, top * ui, clip=False)
        x0, y0 = ox + rx - m, ah - oy - ry - m  # the image's top left in the first tile
        # pans are exact, so each tile is a pan away from the first (view_to_region can be a
        # pixel or two off, so it does not check them)
        panned = (0, 0)

        self.tmp = tempfile.mkdtemp(prefix="nodefmt-capture-")
        canvas = np.zeros((bh, bw, 3), np.uint8)
        mask = np.zeros((bh, bw), bool)
        for j in range(ny):
            for i in range(nx):
                k = j * nx + i
                self.text = f"{self.name}: tile {k + 1}/{self.tiles} ({bw} x {bh} px)"
                dx, dy = i * sx - panned[0], j * sy - panned[1]
                if dx or dy:
                    with self._override():
                        bpy.ops.view2d.pan(deltax=dx, deltay=-dy)
                    panned = (i * sx, j * sy)
                self._redraw()
                shot = self._shoot()
                tile = shot[uy0:uy0 + uh, ux0:ux0 + uw]
                rects = []
                if i:
                    rects.append((0, uh, 0, OVERLAP + REACH))  # the strip shared with the left tile
                if j:
                    rects.append((0, OVERLAP + REACH, 0, uw))  # with the tile above
                self.matches.append(place(canvas, mask, tile, ux0 + i * sx - x0, uy0 + j * sy - y0, rects))
                self.factor = 0.85 * (k + 1) / self.tiles
                yield
        if not mask.all():  # nothing should be left, but never leave black holes
            canvas[~mask] = canvas[np.unravel_index(np.argmax(mask), mask.shape)]
        off = [mm for mm in self.matches if mm[2] is not None and mm[2] > 0.05]
        if off:
            self.warnings.append(f"{len(off)} tiles do not line up exactly with their neighbours")
        self._restore()
        self.text = f"{self.name}: saving {bw} x {bh} px"
        yield
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        writer = png_steps(self.path, canvas)
        try:
            for f in writer:
                self.factor = 0.85 + 0.15 * f
                yield
        finally:
            writer.close()
        self.done = True
        del canvas, mask
        if opt.clipboard:
            self._clipboard()
        if opt.open_image:
            self._open_image()

    # after saving ----------------------------------------------------------------------------

    def _load(self):
        """The saved image as an image data-block (reloaded if it was loaded before)."""
        if self.image is None:
            before = {im.as_pointer() for im in bpy.data.images}
            self.image = bpy.data.images.load(self.path, check_existing=True)
            self.own_image = self.image.as_pointer() not in before
            self.image.reload()
        return self.image

    def _clipboard(self):
        """Copy the saved image to the clipboard (image.clipboard_copy on the image)."""
        im = self._load()
        try:
            with bpy.context.temp_override(window=self.win, edit_image=im):
                ok = bpy.ops.image.clipboard_copy() == {'FINISHED'}
        except RuntimeError as e:
            ok = False
            self.warnings.append(f"could not copy to the clipboard: {e}")
        else:
            if not ok:
                self.warnings.append("could not copy to the clipboard")
        self.copied = ok
        if not self.opt.open_image and self.own_image:  # an image the file had stays
            bpy.data.images.remove(im)
            self.image = None

    def _open_image(self):
        """Show the saved image in an Image Editor of the window, or in a new window."""
        im = self._load()
        area = next((a for a in self.win.screen.areas if a.type == 'IMAGE_EDITOR'), None)
        win = self.win
        if area is None:
            before = set(w.as_pointer() for w in bpy.context.window_manager.windows)
            with bpy.context.temp_override(window=self.win):
                bpy.ops.wm.window_new()
            win = next((w for w in bpy.context.window_manager.windows if w.as_pointer() not in before), None)
            if win is None:
                self.warnings.append("could not open a window for the image")
                return
            area = max(win.screen.areas, key=lambda a: a.width * a.height)
            area.ui_type = 'IMAGE_EDITOR'
        area.spaces.active.image = im
        region = next(r for r in area.regions if r.type == 'WINDOW')
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.image.view_all(fit_view=True)

    def report(self):
        """A one-line summary of the result."""
        w, h = self.size
        mb = os.path.getsize(self.path) / 1e6
        extra = ", copied to the clipboard" if self.copied else ""
        return (f"Saved {self.path} ({w} x {h} px, {mb:.1f} MB, {self.tiles} tiles, "
                f"{time.perf_counter() - self.t0:.1f} s{extra})")
