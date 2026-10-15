"""Render the demo animation: how nodefmt sorts a node tree, step by step.

    python tools/animate.py tree.json out_dir [--fps 30] [--width 1920] [--height 800] [--font PATH]
        [--webp-quality 70] [--gif-fps 15] [--still FRAME]

tree.json comes from tools/dump_tree.py (a messy tree made by tools/scramble.py). The script runs
nodefmt on it offline (no Blender) with snapshots on and renders, as a schematic in Blender's
colours, the steps from the tree as dumped to the 'final' snapshot (what Blender will draw):

1. the tree as it is, with Blender's curved links;
2. links become direct lines (reroutes removed, nodes linked directly);
3. ranking: every node slides into its column (keeping the order in each column);
4. ordering: the columns take their final order, left to right;
5. placement: nodes settle at their final heights;
6. routing: the orthogonal wires draw in, reroutes pop in;
7. the result.

The start, the result, the columns, the copies of input nodes and the final order are nodefmt's;
the motion between them is eased, so steps 3 to 5 illustrate the phases rather than replay the
search. Writes out_dir/nodefmt-demo.mp4 (H.264, width x height), nodefmt-demo.webp (half size)
and nodefmt-demo.gif (half size, fewer frames); --still renders one frame to still.png instead.
Needs Pillow, numpy and PyAV.
"""

import argparse
import glob
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodefmt import dup, rules, wires
from nodefmt.layout import Formatter
from nodefmt.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# socket colours (Blender 5, node_socket.cc)
SOCKET = {
    "GEOMETRY": (0, 214, 163),
    "VALUE": (161, 161, 161),
    "INT": (89, 140, 92),
    "BOOLEAN": (204, 166, 214),
    "VECTOR": (99, 99, 199),
    "STRING": (112, 178, 255),
    "RGBA": (199, 199, 41),
    "ROTATION": (165, 110, 200),
    "MENU": (102, 102, 102),
    "OBJECT": (237, 158, 74),
    "COLLECTION": (245, 245, 245),
    "MATRIX": (184, 51, 133),
    "SHADER": (99, 199, 99),
    "IMAGE": (199, 140, 102),
    "MATERIAL": (235, 117, 117),
}
TAG_THEME = {
    "CONVERTER": "converter_node",
    "INTERFACE": "group_socket_node",
    "GROUP": "group_node",
    "INPUT": "input_node",
    "OUTPUT": "output_node",
    "GEOMETRY": "geometry_node",
    "ATTRIBUTE": "attribute_node",
    "VECTOR": "vector_node",
    "COLOR": "color_node",
    "TEXTURE": "texture_node",
    "SHADER": "shader_node",
    "SCRIPT": "script_node",
    "FILTER": "filter_node",
    "MATTE": "matte_node",
    "DISTORT": "distor_node",
    "PATTERN": "texture_node",
}
ZONE_THEME = {
    "GeometryNodeRepeatInput": "repeat_zone",
    "GeometryNodeSimulationInput": "simulation_zone",
    "GeometryNodeForeachGeometryElementInput": "foreach_geometry_element_zone",
    "NodeClosureInput": "closure_zone",
    "ShaderNodeRepeatInput": "repeat_zone",
}
HEADER = 20.0  # node header height (a widget unit)
GAP = 20.0  # vertical space between nodes stacked in a column
CAPTIONS = [
    "A messy node tree",
    "1. Read the graph: drop reroutes, links as direct lines",
    "2. Rank: each node gets a column",
    "3. Order: reorder columns to remove crossings",
    "4. Place: settle heights, straighten links",
    "5. Route: orthogonal wires on reroutes",
    "Formatted: same logic, no curves, nothing behind nodes",
]


# ---------------------------------------------------------------- easing and helpers
def ease(t):
    """Ease in and out (cubic)."""
    t = min(max(t, 0.0), 1.0)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def back_out(t):
    """Ease out with a small overshoot (reroutes popping in)."""
    t = min(max(t, 0.0), 1.0)
    c = 1.7
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def mix(a, b, t):
    """Linear interpolation from a to b at t (0..1)."""
    return a + (b - a) * t


def rgb(c, k=1.0):
    """A colour (0..1 floats, times k) as an RGB tuple of 0-255 ints."""
    return tuple(round(min(max(v * k, 0.0), 1.0) * 255) for v in c[:3])


def blend(fg, bg, a):
    """fg over bg with alpha a (both 0-255 tuples)."""
    return tuple(round(bg[i] + (fg[i] - bg[i]) * a) for i in range(3))


def pav(desired, heights):
    """Tops for items stacked in this order, as close to `desired` as possible without overlap
    (isotonic regression, pool adjacent violators)."""
    off, acc = [], 0.0
    for h in heights:
        off.append(acc)
        acc += h + GAP
    z = [d - o for d, o in zip(desired, off)]
    blocks = []  # [sum, count]
    for v in z:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    fit = []
    for s, c in blocks:
        fit += [s / c] * c
    return [f + o for f, o in zip(fit, off)]


def crossings(segs):
    """Number of proper crossings between straight segments [(a, b, source)]."""

    def orient(p, q, r):
        """Turn direction of p, q, r: 1, -1, or 0 when collinear."""
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return 0 if abs(v) < 1e-6 else (1 if v > 0 else -1)

    n = 0
    for i in range(len(segs)):
        a, b, s = segs[i]
        for j in range(i + 1, len(segs)):
            c, d, t = segs[j]
            if s == t:
                continue
            if orient(a, b, c) * orient(a, b, d) < 0 and orient(c, d, a) * orient(c, d, b) < 0:
                n += 1
    return n


# ---------------------------------------------------------------- the tree and its states
class Demo:
    """The tree, the formatter's result and the keyframe states (node positions)."""

    def __init__(self, path, select=None):
        """Load a dumped tree (tools/dump_tree.py), format it offline with the rules `select`
        (as in nodefmt.toml; default: the default rules) and build the states."""
        with open(path) as f:
            J = json.load(f)
        self.theme, self.tag, self.ztype = J["theme"], J["color_tag"], J.get("zone_type", {})
        data = J["data"]
        self.orig = json.loads(json.dumps(data["nodes"]))  # the tree as it is (before copies)
        self.osrc = {(tuple(d), sid): tuple(s) for s, d, _, sid in data["links"]}
        self.w = 1.0  # 0: draw nodes and links as they are, 1: as nodefmt models them (copies)
        cfg = rules.Config(rules.resolve(select) if select else rules.DEFAULT)
        orig = set(data["nodes"])
        before = {n: (v["x"], v["y"]) for n, v in data["nodes"].items()}  # where the nodes are now
        with rules.applied(cfg):
            plan = dup.plan(data, "relayout")
            if dup.changes(plan, data):
                data, _ = dup.apply_model(data, plan)
            self.F = F = Formatter(Model(data), record=True, rules=cfg.rules).run()
        self.m = m = F.m
        self.final = next(s for s in F.snapshots if s["phase"] == "final")  # what Blender will draw
        self.names = sorted(m.real)
        self.copies = {n for n in self.names if n not in orig}  # input nodes nodefmt copied
        for n in self.copies:  # a copy shows the colour of what it copies
            src = m.info[n].get("dupkey")
            twin = next((o for o in orig if m.info.get(o, {}).get("dupkey") == src), None)
            self.tag[n] = self.tag.get(twin, "INTERFACE")
        self.zones = [(z["name"], m.paired(z["name"]), set(z["nodes"])) for z in self.final["zones"]]
        self.frames = []
        for f in m.frames:
            kids = [n for n in self.names if self._inside(n, f)]
            if kids:
                self.frames.append((f, m.info[f].get("label") or "", kids, m.pads.get(f, (30, 40, 30, 30))))
        start = {n: before.get(n, (m.box[n][0], m.box[n][1])) for n in self.names}
        end = {n["name"]: (n["x"], n["y"]) for n in self.final["nodes"]}
        for n in self.copies:
            start[n] = end[n]
        self.start, self.end = start, end
        self._columns()

    def _inside(self, n, f):
        """True if node n is inside frame f, at any depth."""
        p = self.m.parent(n)
        while p is not None:
            if p == f:
                return True
            p = self.m.parent(p)
        return False

    def ext(self, n):
        """Room above and below node n taken by the frames around it."""
        top = bot = 0.0
        for f, _, kids, pad in self.frames:
            if n in kids:
                top += pad[1]
                bot += pad[3]
        return top, bot

    def height(self, n):
        """Height of node n plus the frame padding above and below it."""
        t, b = self.ext(n)
        return self.m.box[n][3] + t + b

    def stack(self, order, desired):
        """Tops of the nodes of one column in `order`, near their `desired` tops."""
        tops = pav([desired[n] - self.ext(n)[0] for n in order], [self.height(n) for n in order])
        return {n: t + self.ext(n)[0] for n, t in zip(order, tops)}

    def _columns(self):
        """Columns from the final x positions; the ranked state and the order sweep."""
        m, end, start = self.m, self.end, self.start
        nodes = sorted(self.names, key=lambda n: end[n][0])
        cols, right = [], None
        for n in nodes:
            x0, x1 = end[n][0], end[n][0] + m.box[n][2]
            if cols and x0 < right - 10:
                cols[-1].append(n)
                right = max(right, x1)
            else:
                cols.append([n])
                right = x1
        self.cols = cols
        # ranked: final x, the old vertical order kept, stacked near the old heights
        ranked = {}
        for c in cols:
            order = sorted(c, key=lambda n: (start[n][1], n))
            ys = self.stack(order, {n: start[n][1] for n in c})
            for n in c:
                ranked[n] = (end[n][0], ys[n])
        self.ranked = ranked
        # the order sweep: column after column takes its final order, in the slots it had
        self.sweep = [dict(ranked)]
        cur = dict(ranked)
        for c in cols:
            old = sorted(c, key=lambda n: (cur[n][1], n))
            new = sorted(c, key=lambda n: (end[n][1], n))
            if old == new:
                continue
            slots = [cur[n][1] for n in old]
            ys = self.stack(new, {n: s for n, s in zip(new, slots)})
            cur = dict(cur)
            for n in c:
                cur[n] = (end[n][0], ys[n])
            self.sweep.append(cur)
        self.ordered = cur

    # ------------------------------------------------------------ geometry of a state
    def box(self, n, pos):
        """Box (x0, y0, x1, y1) of node n at positions `pos`; its height blends from
        the original to the modelled one with self.w."""
        x, y = pos[n]
        h = self.m.box[n][3]
        if n in self.orig and self.w < 1:
            h = mix(self.orig[n]["h"], h, self.w)
        return x, y, x + self.m.box[n][2], y + h

    def sockets(self, n):
        """The sockets of node n as drawn at self.w (a copied input node shows fewer)."""
        if n in self.orig and self.w < 0.5:
            return self.orig[n].get("socks", {})
        return self.m.info[n].get("socks", {})

    def model_links(self, pos):
        """Every link as (a, b, type, source) between socket positions, nodes at `pos`. Below
        self.w = 1 a link starts (partly) from the socket that feeds it in the original tree:
        nodefmt's copies of input nodes take over links from the originals."""
        m = self.m
        out = []
        for s, d, _, sid in self.F.links:
            k = m.slot_key(s, d, sid)
            (ax, ay), (bx, by) = pos[s[0]], pos[d[0]]
            oa, ob = m.outs[s[0]][s], m.ins[d[0]][k]
            a = (ax + oa[0], ay + oa[1])
            o = self.osrc.get((tuple(d), sid))
            if self.w < 1 and o is not None and o[0] in pos:
                off = self.orig[o[0]]["socks"][f"o{o[2]}"]["off"]
                p = (pos[o[0]][0] + off[0], pos[o[0]][1] + off[1])
                a = (mix(p[0], a[0], self.w), mix(p[1], a[1], self.w))
            out.append((a, (bx + ob[0], by + ob[1]), m.sock_type.get(s), s))
        return out

    def frame_rects(self, pos):
        """(label, box) of every frame around its nodes at positions `pos`."""
        out = []
        for f, label, kids, (pl, pt, pr, pb) in self.frames:
            bs = [self.box(n, pos) for n in kids]
            out.append(
                (
                    label,
                    (
                        min(b[0] for b in bs) - pl,
                        min(b[1] for b in bs) - pt,
                        max(b[2] for b in bs) + pr,
                        max(b[3] for b in bs) + pb,
                    ),
                )
            )
        return out

    def zone_polys(self, pos):
        """(zone type, outline polygon) of every zone at positions `pos`."""
        out = []
        for zin, zout, nodes in self.zones:
            content = [self.box(n, pos) for n in sorted(nodes) if n not in (zin, zout) and n in pos]
            poly = wires.zone_outline(self.box(zin, pos), self.box(zout, pos) if zout in pos else None, content)
            out.append((self.ztype.get(zin, ""), poly))
        return out

    def bounds(self, pos, routed=False):
        """Bounding box of nodes, frames and zones at `pos` (routed: also the final wires)."""
        xs, ys = [], []
        for n in pos:
            b = self.box(n, pos)
            xs += [b[0], b[2]]
            ys += [b[1], b[3]]
        for _, r in self.frame_rects(pos):
            xs += [r[0], r[2]]
            ys += [r[1], r[3]]
        for _, poly in self.zone_polys(pos):
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        if routed:
            for lk in self.final["links"]:
                xs += [lk["a"][0], lk["b"][0]]
                ys += [lk["a"][1], lk["b"][1]]
        return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------- the timeline
class Timeline:
    """Per frame: node positions, link style, routing progress, caption."""

    def __init__(self, demo, fps):
        """Build every frame of the animation of `demo` at `fps`."""
        self.d, self.fps = demo, fps
        self.frames = []
        d = demo

        def S(s):
            return round(s * fps)

        def hold(pos, n, **kw):
            """Add n frames that keep positions `pos`."""
            for _ in range(n):
                self.frames.append(dict(pos=pos, **kw))

        def move(a, b, n, delay=None, **kw):
            """Ease from a to b over n frames; delay(node) in 0..0.4 staggers the start."""
            for i in range(n):
                t = (i + 1) / n
                pos = {}
                for k in a:
                    dl = delay(k) if delay else 0.0
                    u = ease((t - dl) / (1 - 0.4)) if delay else ease(t)
                    pos[k] = (mix(a[k][0], b[k][0], u), mix(a[k][1], b[k][1], u))
                self.frames.append(dict(pos=pos, **kw))

        # 0: the messy tree
        hold(d.start, S(1.8), curve=1.0, cap=0, w=0.0)
        # 1: curves become direct lines
        for i in range(S(1.2)):
            self.frames.append({"pos": d.start, "curve": 1 - ease((i + 1) / S(1.2)), "cap": 1, "w": 0.0})
        hold(d.start, S(0.6), curve=0.0, cap=1, w=0.0)
        # 2: ranking (copies of input nodes fade in at their column and take over links)
        left = d.bounds(d.ranked)[0]
        xr = {n: d.ranked[n][0] - left for n in d.names}
        span = max(xr.values()) or 1.0
        n2 = S(1.8)
        for i in range(n2):
            t = (i + 1) / n2
            pos = {}
            for k in d.names:
                u = ease((t - 0.3 * xr[k] / span) / 0.7)
                pos[k] = (mix(d.start[k][0], d.ranked[k][0], u), mix(d.start[k][1], d.ranked[k][1], u))
            self.frames.append({"pos": pos, "curve": 0.0, "cap": 2, "w": ease(t)})
        hold(d.ranked, S(0.6), curve=0.0, cap=2)
        # 3: ordering, column by column, overlapping
        steps = d.sweep
        per = S(0.55)
        if len(steps) > 1:
            total = per * (len(steps) - 1) + per
            for i in range(total):
                # step j eases from steps[j] to steps[j + 1] during frames [j * per, (j + 2) * per)
                cur = dict(steps[0])
                for j in range(len(steps) - 1):
                    u = ease((i + 1 - j * per) / (2 * per))
                    if u <= 0:
                        break
                    a, b = steps[j], steps[j + 1]
                    for n in d.names:
                        if a[n] != b[n]:
                            # nodes moving up pass on the left, nodes moving down on the right
                            side = 35.0 * math.sin(math.pi * u) * (1 if b[n][1] > a[n][1] else -1)
                            cur[n] = (mix(cur[n][0], b[n][0], u) + side, mix(cur[n][1], b[n][1], u))
                self.frames.append({"pos": cur, "curve": 0.0, "cap": 3})
        hold(d.ordered, S(0.6), curve=0.0, cap=3)
        # 4: placement, staggered by column
        colx = {n: ci / max(1, len(d.cols) - 1) for ci, c in enumerate(d.cols) for n in c}
        move(d.ordered, d.end, S(1.8), delay=lambda n: 0.4 * colx[n], curve=0.0, cap=4)
        hold(d.end, S(0.5), curve=0.0, cap=4)
        # 5: routing: a front sweeps left to right
        x0, _, x1, _ = d.bounds(d.end, routed=True)
        n5 = S(2.6)
        for i in range(n5):
            front = mix(x0 - 40, x1 + 120, ease((i + 1) / n5))
            self.frames.append({"pos": d.end, "curve": 0.0, "cap": 5, "front": front})
        # 6: the result
        hold(d.end, S(2.6), curve=0.0, cap=6, front=1e9)
        self.loop = S(0.6)  # cross-fade back to the first frame


# ---------------------------------------------------------------- rendering
def find_font(path=None):
    """A font file: `path`, else Blender's own UI font (Inter, from BLENDER_DIR, the folder of the
    Blender executable, or a default install), else a common system font."""
    cands = [path] if path else []
    for base in (
        os.environ.get("BLENDER_DIR"),
        r"C:\Program Files\Blender Foundation\Blender 5.2",
        "/usr/share/blender",
        "/Applications/Blender.app/Contents/Resources",
    ):
        if base:
            cands += sorted(glob.glob(os.path.join(base, "*", "datafiles", "fonts", "Inter.woff2")))
            cands.append(os.path.join(base, "datafiles", "fonts", "Inter.woff2"))
    cands += [r"C:\Windows\Fonts\segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


class Renderer:
    """Draws one frame of the animation with Pillow, supersampled by `ss`."""

    def __init__(self, demo, W, H, font, ss=2):
        """Renderer of `demo` for a W x H output; colours from the dumped Blender theme."""
        self.d, self.W, self.H, self.ss = demo, W, H, ss
        self.font_path = font
        self._fonts = {}
        th = demo.theme
        self.back = rgb(th.get("back", (0.11, 0.11, 0.11)))
        self.body = rgb(th.get("node_backdrop", (0.19, 0.19, 0.19)))
        self.wire = rgb(th.get("wire", (0.1, 0.1, 0.1)))
        self.bar = 44 * ss  # caption band height (render pixels)

    def font(self, px, bold=False):
        """The UI font at `px` pixels (cached), or Pillow's default font."""
        key = (int(px), bold)
        if key not in self._fonts:
            try:
                f = ImageFont.truetype(self.font_path, int(px))
                if bold:
                    try:
                        f.set_variation_by_axes([620])
                    except Exception:  # noqa: BLE001, S110 - not a variable font: the regular weight
                        pass
            except Exception:  # noqa: BLE001 - no usable font file: Pillow's default font
                f = ImageFont.load_default()
            self._fonts[key] = f
        return self._fonts[key]

    def header(self, n):
        """Header colour of node n, from its colour tag and the theme."""
        key = TAG_THEME.get(self.d.tag.get(n, "NONE"), "group_socket_node")
        return rgb(self.d.theme.get(key, (0.3, 0.3, 0.3)))

    def frame(self, st, cam, cap_mix):
        """Render state `st` seen through camera `cam`, with the caption band; returns an image."""
        d, ss = self.d, self.ss
        W, H = self.W * ss, self.H * ss
        im = Image.new("RGB", (W, H), self.back)
        dr = ImageDraw.Draw(im)
        sc, ox, oy = cam

        def P(p):
            return ((p[0] - ox) * sc, (p[1] - oy) * sc + self.bar)

        def L(u, lo=0.0):
            return max(u * sc, lo * ss)  # a length in node units, at least lo output px

        pos = st["pos"]
        d.w = st.get("w", 1.0)
        alpha = {n: d.w for n in d.copies}
        # dot grid
        step = 100.0
        g = blend((255, 255, 255), self.back, 0.07)
        gx0 = math.floor(ox / step) * step
        gy0 = math.floor(oy / step) * step
        r = max(1.0, 1.2 * ss)
        x = gx0
        while (x - ox) * sc < W:
            y = gy0
            while (y - oy) * sc < H:
                px, py = P((x, y))
                if py > self.bar:
                    dr.ellipse([px - r, py - r, px + r, py + r], fill=g)
                y += step
            x += step
        # zones and frames
        for zt, poly in d.zone_polys(pos):
            c = d.theme.get(ZONE_THEME.get(zt, "repeat_zone"), (0.46, 0.32, 0.18, 0.2))
            fill = blend(rgb(c), self.back, 0.20)
            line = blend(rgb(c), self.back, 0.55)
            dr.polygon([P(p) for p in poly], fill=fill, outline=line, width=max(1, int(1.0 * ss)))
        for label, (x0, y0, x1, y1) in d.frame_rects(pos):
            fc = d.theme.get("frame_node", (0.06, 0.06, 0.06, 0.8))
            dr.rounded_rectangle([P((x0, y0)), P((x1, y1))], radius=L(6), fill=blend(rgb(fc), self.back, fc[3]))
            if label:
                f = self.font(max(L(16), 7 * ss))
                tw = dr.textlength(label, font=f)
                cx = P(((x0 + x1) / 2, y0))[0]
                if tw < (x1 - x0) * sc:
                    dr.text((cx - tw / 2, P((x0, y0 + 6))[1]), label, font=f, fill=(225, 225, 225))
        # links
        wi, wo = L(2.6, 1.6), L(4.4, 2.6)
        front = st.get("front")
        model = d.model_links(pos)
        curve = st.get("curve", 0.0)
        for a, b, typ, s in model:
            fade = 1.0
            if front is not None:
                span = max(b[0] - a[0], 1.0)
                fade = 1.0 - min(max((front - a[0]) / span, 0.0), 1.0)
                fade *= 0.55
                if fade <= 0.01:
                    continue
            k = 1.0
            pts = self.noodle(a, b, curve)
            col = SOCKET.get(typ, (160, 160, 160))
            dr.line([P(p) for p in pts], fill=blend(self.wire, self.back, fade * k), width=int(wo), joint="curve")
            dr.line([P(p) for p in pts], fill=blend(col, self.back, fade * k), width=int(wi), joint="curve")
        if front is not None:
            self.routes(dr, P, L, front, wi, wo)
        # nodes
        for n in sorted(d.names, key=lambda n: (n not in d.copies, n)):
            k = alpha.get(n, 1.0)
            if k <= 0.01:
                continue
            self.node(dr, n, pos, P, L, k)
        # reroutes
        if front is not None:
            for r in d.final["reroutes"]:
                t = back_out((front - r["x"]) / 60.0) if front < 1e8 else 1.0
                if t <= 0:
                    continue
                typ = d.m.sock_type.get(tuple(r["src"]))
                rad = L(4.5, 2.4) * t
                c = P((r["x"], r["y"]))
                dr.ellipse([c[0] - rad - ss, c[1] - rad - ss, c[0] + rad + ss, c[1] + rad + ss], fill=self.wire)
                dr.ellipse([c[0] - rad, c[1] - rad, c[0] + rad, c[1] + rad], fill=SOCKET.get(typ, (200, 200, 200)))
        self.caption(dr, st, cap_mix)
        return im

    def noodle(self, a, b, curve):
        """Blender's link curve (noodle curving 4) scaled by `curve`, as points."""
        if curve <= 1e-3:
            return [a, b]
        h = curve * 0.4 * abs(b[0] - a[0])
        c1, c2 = (a[0] + h, a[1]), (b[0] - h, b[1])
        pts = []
        for i in range(25):
            t = i / 24
            u = 1 - t
            pts.append(
                (
                    u**3 * a[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * b[0],
                    u**3 * a[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * b[1],
                )
            )
        return pts

    def routes(self, dr, P, L, front, wi, wo):
        """The routed wires up to the front: horizontal runs grow to the right, vertical runs
        grow from their upstream end once the front passes them."""
        d = self.d
        segs = []
        for lk in d.final["links"]:
            a, b = lk["a"], lk["b"]
            col = SOCKET.get(lk.get("type"), (160, 160, 160))
            if abs(a[1] - b[1]) < 0.5:  # horizontal
                lo, hi = min(a[0], b[0]), max(a[0], b[0])
                if front <= lo:
                    continue
                e = min(front, hi)
                p, q = (lo, a[1]), (e, a[1])
            else:
                t = min(max((front - a[0]) / 40.0, 0.0), 1.0) if front < 1e8 else 1.0
                if t <= 0:
                    continue
                p, q = tuple(a), (mix(a[0], b[0], t), mix(a[1], b[1], t))
            segs.append((P(p), P(q), col))
        for p, q, col in segs:
            dr.line([p, q], fill=self.wire, width=int(wo))
        for p, q, col in segs:
            dr.line([p, q], fill=col, width=int(wi))

    def node(self, dr, n, pos, P, L, k):
        """Draw node n at `pos`: body, header, label and sockets."""
        d, ss = self.d, self.ss
        x0, y0, x1, y1 = d.box(n, pos)
        a, b = P((x0, y0)), P((x1, y1))
        rad = L(5)
        bg = self.back
        body = blend(self.body, bg, k)
        head = blend(self.header(n), bg, k)
        dr.rounded_rectangle(
            [a[0] - ss, a[1] - ss, b[0] + ss, b[1] + ss], radius=rad + ss, fill=blend((10, 10, 10), bg, k)
        )
        dr.rounded_rectangle([a, b], radius=rad, fill=body)
        hb = P((x1, y0 + HEADER))[1]
        dr.rounded_rectangle([a[0], a[1], b[0], hb], radius=rad, fill=head, corners=(True, True, False, False))
        # title
        info = d.m.info[n]
        title = info.get("label") or info.get("title") or n
        fpx = max(L(11), 7.4 * ss)
        if hb - a[1] >= 3 * ss:
            f = self.font(fpx)
            room = (b[0] - a[0]) - L(10, 3)
            text = title
            while text and dr.textlength(text, font=f) > room:
                text = text[:-1]
            if text != title:
                text = text[:-1].rstrip() + "\u2026" if len(text) > 3 else ""
            if text:
                dr.text(
                    (a[0] + L(6, 2.5), (a[1] + hb) / 2), text, font=f, anchor="lm", fill=blend((235, 235, 235), bg, k)
                )
        # sockets
        rr = L(3.6, 2.0)
        for s in d.sockets(n).values():
            if not s.get("vis"):
                continue
            c = P((x0 + s["off"][0], y0 + s["off"][1]))
            col = blend(SOCKET.get(s["type"], (160, 160, 160)), bg, k)
            dr.ellipse(
                [c[0] - rr - ss * 0.8, c[1] - rr - ss * 0.8, c[0] + rr + ss * 0.8, c[1] + rr + ss * 0.8],
                fill=blend((15, 15, 15), bg, k),
            )
            dr.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr], fill=col)

    def caption(self, dr, st, cap_mix):
        """Draw the caption band: the step's caption (cross-faded), the step dots and the
        crossing count."""
        ss = self.ss
        W = self.W * ss
        dr.rectangle([0, 0, W, self.bar], fill=blend((255, 255, 255), self.back, 0.045))
        dr.line([0, self.bar, W, self.bar], fill=blend((255, 255, 255), self.back, 0.10), width=ss)
        f = self.font(self.bar * 0.42, bold=True)
        cur, prev, t = cap_mix
        for idx, a in ((prev, 1 - 2 * t), (cur, 2 * t - 1)):  # the old one fades out, then the new one in
            if idx is None or a <= 0.01:
                continue
            dr.text(
                (self.bar * 0.42, self.bar / 2),
                CAPTIONS[idx],
                font=f,
                anchor="lm",
                fill=blend((240, 240, 240), blend((255, 255, 255), self.back, 0.045), a),
            )
        # step dots
        r = self.bar * 0.09
        for i in range(5):
            cx = W - self.bar * 0.42 - (4 - i) * r * 4.2
            on = 1 <= cur <= 6 and i + 1 <= cur
            col = (240, 240, 240) if on else blend((255, 255, 255), self.back, 0.25)
            dr.ellipse([cx - r, self.bar / 2 - r, cx + r, self.bar / 2 + r], fill=col)
        hud = st.get("hud")
        if hud:
            fs = self.font(self.bar * 0.32)
            dr.text(
                (W - self.bar * 0.42 - 4 * r * 4.2 - r * 3, self.bar / 2),
                hud,
                font=fs,
                anchor="rm",
                fill=(170, 170, 170),
            )


def cameras(demo, tl, W, H, bar, ss):
    """Per frame (scale, x0, y0): the content fitted below the caption band, smoothed."""
    boxes = []
    for st in tl.frames:
        demo.w = st.get("w", 1.0)
        b = demo.bounds(st["pos"], routed=st.get("front") is not None)
        boxes.append(b)
    arr = np.array(boxes, float)
    k = int(tl.fps * 0.8) | 1
    pad = np.pad(arr, ((k // 2, k // 2), (0, 0)), mode="edge")
    ker = np.ones(k) / k
    sm = np.stack([np.convolve(pad[:, i], ker, mode="valid") for i in range(4)], axis=1)
    out = []
    mx, my = 36 * ss, 26 * ss
    for x0, y0, x1, y1 in sm:
        aw, ah = W * ss - 2 * mx, H * ss - bar - 2 * my
        sc = min(aw / (x1 - x0), ah / (y1 - y0))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        out.append((sc, cx - (W * ss / 2) / sc, cy - ((H * ss - bar) / 2) / sc))
    return out


def main():
    """Build the timeline and render the MP4, WebP and GIF (or one still frame)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("out")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=800)
    ap.add_argument("--font", default=None)
    ap.add_argument("--webp-quality", type=int, default=70)
    ap.add_argument("--gif-fps", type=int, default=15)
    ap.add_argument("--still", type=int, default=None, help="render only this frame to out/still.png")
    ap.add_argument("--select", default=None, help="rules to sort with, as in nodefmt.toml (e.g. ALL)")
    a = ap.parse_args()
    import av

    os.makedirs(a.out, exist_ok=True)
    demo = Demo(a.tree, a.select.split(",") if a.select else None)
    tl = Timeline(demo, a.fps)
    # crossings of the direct lines, shown in the caption band
    cache = {}
    for st in tl.frames:
        demo.w = st.get("w", 1.0)
        if st.get("front") is not None:
            key = "final"
            if key not in cache:
                segs = [(tuple(lk["a"]), tuple(lk["b"]), tuple(lk["src"])) for lk in demo.final["links"]]
                cache[key] = crossings(segs)
        else:
            key = (
                round(demo.w, 3),
                st.get("curve", 0) < 0.5,
                tuple(sorted((n, round(p[0]), round(p[1])) for n, p in st["pos"].items())),
            )
            if key not in cache:
                segs = [(p, q, s) for p, q, _, s in demo.model_links(st["pos"])]
                cache[key] = crossings(segs) if st.get("curve", 0) < 0.5 else None
        c = cache[key]
        st["hud"] = f"{c} crossings" if c is not None else ""
    direct = max(i for i, st in enumerate(tl.frames) if st["cap"] == 1)
    print(
        "direct lines:",
        tl.frames[direct]["hud"],
        "| result:",
        tl.frames[-1]["hud"],
        "| columns",
        len(demo.cols),
        "| order steps",
        len(demo.sweep) - 1,
        "| copies",
        len(demo.copies),
        "| reroutes",
        len(demo.final["reroutes"]),
    )
    font = find_font(a.font)
    r = Renderer(demo, a.width // 2, a.height // 2, font, ss=4)
    cams = cameras(demo, tl, r.W, r.H, r.bar, r.ss)
    n = len(tl.frames)
    caps = [st["cap"] for st in tl.frames]

    def cap_mix(i):
        """Caption of frame i, the previous caption and the fade between them."""
        cur = caps[i]
        j = i
        while j > 0 and caps[j - 1] == cur:
            j -= 1
        t = min(1.0, (i - j + 1) / (a.fps * 0.4))
        return cur, (caps[j - 1] if j > 0 else None), (t if j > 0 else 1.0)

    def render(i):
        """Frame i rendered and scaled down to the output size."""
        im = r.frame(tl.frames[i], cams[i], cap_mix(i))
        return im.resize((a.width, a.height), Image.LANCZOS)

    if a.still is not None:
        render(a.still).save(os.path.join(a.out, "still.png"))
        return
    mp4 = os.path.join(a.out, "nodefmt-demo.mp4")
    small = []
    first = None
    with av.open(mp4, "w") as out:
        s = out.add_stream("libx264", rate=a.fps)
        s.width, s.height, s.pix_fmt = a.width, a.height, "yuv420p"
        s.options = {"crf": "18", "preset": "slow"}
        for i in range(n + tl.loop):
            if i < n:
                im = render(i)
                if first is None:
                    first = im
                last = im
            else:  # cross-fade into the first frame, so the loop is seamless
                t = ease((i - n + 1) / tl.loop)
                im = Image.blend(last, first, t)
            for p in s.encode(av.VideoFrame.from_image(im)):
                out.mux(p)
            small.append(im.resize((a.width // 2, a.height // 2), Image.LANCZOS))
            if i % 60 == 0:
                print("frame", i, "/", n + tl.loop, flush=True)
        for p in s.encode():
            out.mux(p)
    ms = 1000.0 / a.fps
    durs = [round((i + 1) * ms) - round(i * ms) for i in range(len(small))]
    webp = os.path.join(a.out, "nodefmt-demo.webp")
    small[0].save(
        webp,
        save_all=True,
        append_images=small[1:],
        duration=durs,
        loop=0,
        quality=a.webp_quality,
        method=6,
        minimize_size=True,
    )
    step = max(1, round(a.fps / a.gif_fps))
    gif_frames = small[::step]
    # one palette for all frames, from frames spread over the whole animation
    picks = gif_frames[:: max(1, len(gif_frames) // 8)]
    sheet = Image.new("RGB", (picks[0].width, picks[0].height * len(picks)))
    for k, f in enumerate(picks):
        sheet.paste(f, (0, k * f.height))
    pal = sheet.quantize(colors=192, method=Image.Quantize.FASTOCTREE)
    gq = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in gif_frames]
    gif = os.path.join(a.out, "nodefmt-demo.gif")
    gq[0].save(
        gif,
        save_all=True,
        append_images=gq[1:],
        duration=round(1000 * step / a.fps),
        loop=0,
        optimize=False,
        disposal=1,
    )
    for p in (mp4, webp, gif):
        print(f"{p}: {os.path.getsize(p) / 1e6:.2f} MB")
    print(f"{len(small)} frames, {len(small) / a.fps:.1f} s at {a.fps} fps")


if __name__ == "__main__":
    main()
