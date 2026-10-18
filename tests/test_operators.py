# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the add-on operators: sorting with progress, Esc, undo, Sort Selection, Check,
Capture Tree.

    blender --factory-startup --enable-event-simulate --python tests/test_operators.py

Registers the add-on from this folder (not installed), appends a few examples from examples/
and drives the operators as the panel does (INVOKE_DEFAULT: modal, with progress), letting
Blender run between steps. --enable-event-simulate lets the test press Esc (and blocks real
input while it runs). Prints one line per test and exits 1 if any fails.
"""

import os
import re
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EXAMPLES = ("NF010", "NF032", "NF030")
RESULTS = []


def test(name, ok, info=""):
    """Record and print one result."""
    RESULTS.append(bool(ok))
    print(f"{'ok  ' if ok else 'FAIL'} {name}{': ' + info if info else ''}", flush=True)


def append(code):
    """The node group of examples/<code>.blend, appended."""
    with bpy.data.libraries.load(os.path.join(ROOT, "examples", code + ".blend"), link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
    g = dst.node_groups[0]
    g.use_fake_user = True  # kept by undo
    return g.name


def editor():
    """(window, area, region) of the node editor (the largest area, made one)."""
    win = bpy.context.window_manager.windows[0]
    area = next((a for a in win.screen.areas if a.type == "NODE_EDITOR"), None)
    if area is None:
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.ui_type = "GeometryNodeTree"
    return win, area, next(r for r in area.regions if r.type == "WINDOW")


def override():
    """A context override for the node editor."""
    win, area, region = editor()
    return bpy.context.temp_override(window=win, area=area, region=region)


def show(name):
    """Show group `name` in the node editor."""
    sp = editor()[1].spaces.active
    sp.pin = True
    sp.node_tree = bpy.data.node_groups[name]


def state(names):
    """What a sort changes, for the trees `names`: node and reroute positions and links."""
    from nodefmt import api, check

    return {n: (api._signature(bpy.data.node_groups[n]), check.fingerprint(bpy.data.node_groups[n])) for n in names}


def wait_job(ui, seen, press_esc_after=None):
    """Wait for the running sort to end, keeping each progress text and factor; press Esc
    after `press_esc_after` progress updates (None: never)."""
    for _ in range(4000):
        job = ui._JOB["job"]
        if job is None:
            return
        if not seen or seen[-1] != (job.text, job.factor):
            seen.append((job.text, job.factor))
        if press_esc_after is not None and len(seen) >= press_esc_after:
            editor()[0].event_simulate(type="ESC", value="PRESS")
            press_esc_after = None
        yield 0.02


def run():
    """The tests (a generator: the timer lets Blender run in between)."""
    from nodefmt import ui

    bpy.context.preferences.view.ui_scale = 1.0  # in memory only
    ui.register()
    names = [append(c) for c in EXAMPLES]
    editor()
    yield 0.5
    show(names[1])  # NF032: a zone, so the layout has two containers
    yield 0.3
    with override():
        bpy.ops.ed.undo_push(message="test start")
    start = state(names)

    # Sort Current Tree with progress, then one undo step
    seen = []
    every = []  # the text after every step: the layout of a small tree can run between two samples
    step = ui.SortJob.step

    def logged(job):
        """SortJob.step, keeping the progress text."""
        more = step(job)
        every.append(job.text)
        return more

    ui.SortJob.step = logged
    with override():
        r = bpy.ops.node.nodefmt_sort_tree("INVOKE_DEFAULT", True)
    test("sort current tree starts", r == {"RUNNING_MODAL"}, str(r))
    yield from wait_job(ui, seen)
    ui.SortJob.step = step
    after = state(names)
    test("sort current tree sorts", after[names[1]][0] != start[names[1]][0] and after[names[0]] == start[names[0]])
    test("logic unchanged", after[names[1]][1] == start[names[1]][1])
    texts = [t for t, _ in seen]
    pattern = re.compile(r"Tree 1/1 .+: pass \d+ \(of at most \d+\), .+ \(step \d+/\d+\)$")
    test(
        "progress shown",
        len(seen) >= 3 and all(pattern.match(t) for t in texts[1:]),
        f"{len(seen)} updates, e.g. {texts[len(texts) // 2]!r}",
    )
    factors = [f for _, f in seen]
    test("progress never goes back", factors == sorted(factors), f"{factors[0]:.2f} .. {factors[-1]:.2f}")
    test("layout steps counted", any(re.search(r"layout \d+/\d+", t) for t in every))
    test("status bar cleared", ui._JOB["job"] is None)
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    test("one undo step puts the tree back", state(names) == start)

    # Sort All Trees, cancelled with Esc after a few steps: everything is put back
    seen = []
    with override():
        r = bpy.ops.node.nodefmt_sort_all("INVOKE_DEFAULT", True)
    test("sort all starts", r == {"RUNNING_MODAL"}, str(r))
    yield from wait_job(ui, seen, press_esc_after=8)
    test("Esc cancels", ui._JOB["job"] is None and len(seen) >= 8, f"{len(seen)} updates, last {seen[-1][0]!r}")
    test("Esc puts every tree back", state(names) == start)

    # Sort All Trees to the end, then undo
    seen = []
    with override():
        r = bpy.ops.node.nodefmt_sort_all("INVOKE_DEFAULT", True)
    yield from wait_job(ui, seen)
    after = state(names)
    test("sort all sorts every tree", all(after[n][0] != start[n][0] for n in names))
    test("sort all shows each tree", all(any(t.startswith(f"Tree {k}/") for t, _ in seen) for k in (1, 2, 3)))
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    test("one undo step puts every tree back", state(names) == start)

    # Sort Selection (the frame saved selected in examples/selection.blend): one undo step
    sel = append("selection")
    show(sel)
    yield 0.3
    with override():
        bpy.ops.ed.undo_push(message="before selection")
    before = state([sel])
    with override():
        r = bpy.ops.node.nodefmt_sort_selection("INVOKE_DEFAULT", True)
    yield 0.3
    test("sort selection", r == {"FINISHED"} and state([sel])[sel][0] != before[sel][0], str(r))
    test("sort selection keeps the logic", state([sel])[sel][1] == before[sel][1])
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    test("one undo step puts the selection back", state([sel]) == before)

    # Check: results by rule, each place selected and framed in turn, marks in the editor
    yield from check_tests(ui)

    # scripts: EXEC_DEFAULT sorts at once
    with override():
        r = bpy.ops.node.nodefmt_sort_all("EXEC_DEFAULT", True)
    test("sort all from a script", r == {"FINISHED"} and state(names) != start, str(r))

    # Capture Tree: at two UI scales, the selection, no undo step, Esc
    yield from capture_tests(ui)
    ui.unregister()


def check_tests(ui):
    """Check, Show Violation (select, frame, cycle), the overlay, a stale result, no problems."""
    name = append("NF004")  # two NF004 places, plus NF034, NF010 and not formatted
    show(name)
    yield 0.3
    nt = bpy.data.node_groups[name]
    with override():
        r = bpy.ops.node.nodefmt_check()
    found = [v.code for v in ui._LAST["violations"]]
    test(
        "check finds the rule",
        r == {"FINISHED"} and found.count("NF004") == 2 and "NF900" in found,
        ", ".join(sorted(set(found))),
    )
    test("every place has nodes or a point", all(v.nodes or (v.x, v.y) != (0.0, 0.0) for v in ui._LAST["violations"]))
    region = editor()[2]
    shown = []
    for _ in range(3):
        before = tuple(region.view2d.view_to_region(0, 0, clip=False))
        with override():
            r = bpy.ops.node.nodefmt_show_violation(code="NF004")
        yield 0.2
        selected = {n.name for n in nt.nodes if n.select}
        shown.append((r, ui._LAST["shown"], selected, before != tuple(region.view2d.view_to_region(0, 0, clip=False))))
    test(
        "show selects the place",
        all(
            r == {"FINISHED"} and "Group Input" in sel and any(nt.nodes[k].bl_idname == "NodeReroute" for k in sel)
            for r, _, sel, _ in shown
        ),
        str([sorted(s) for _, _, s, _ in shown][:1]),
    )
    test("show frames the place", any(moved for _, _, _, moved in shown))
    test(
        "show cycles through the places",
        shown[0][1] != shown[1][1] and shown[2][1] == shown[0][1],
        str([k for _, k, _, _ in shown]),
    )
    calls = []

    def probe():
        """Run the overlay's draw function and keep the outcome."""
        try:
            ui._draw_overlay()
            calls.append("ok")
        except Exception as e:  # noqa: BLE001 - the outcome is what is tested
            calls.append(repr(e))

    handle = bpy.types.SpaceNodeEditor.draw_handler_add(probe, (), "WINDOW", "POST_PIXEL")
    with override():
        bpy.ops.wm.redraw_timer(type="DRAW_WIN", iterations=1)
    bpy.types.SpaceNodeEditor.draw_handler_remove(handle, "WINDOW")
    test("overlay draws", calls and all(c == "ok" for c in calls), str(calls[:2]))
    with override():
        test("result is current", ui.checked(bpy.context) is not None)
    nt.nodes["Group Input"].location.x += 40
    with override():
        test("result is stale after an edit", ui.checked(bpy.context) is None)
        test("show is off when stale", not bpy.ops.node.nodefmt_show_violation.poll())
        bpy.ops.node.nodefmt_sort_tree("EXEC_DEFAULT", True)
        bpy.ops.node.nodefmt_check()
    test("no problems after a sort", ui._LAST["violations"] == [], ", ".join(v.code for v in ui._LAST["violations"]))


def editor_state():
    """What a capture changes in the editor and must put back: the view (where view point
    (0, 0) is, region pixels per view unit), the region size, regions, overlays, maximised."""
    win, area, region = editor()
    v = region.view2d
    x0, y0 = v.view_to_region(0, 0, clip=False)
    x1, y1 = v.view_to_region(100000, 100000, clip=False)
    sp = area.spaces.active
    flags = (
        region.width,
        region.height,
        sp.show_region_header,
        sp.show_region_toolbar,
        sp.show_region_ui,
        sp.overlay.show_context_path,
        win.screen.name,
        win.screen.show_fullscreen,
        bpy.context.window_manager.nodefmt_overlay,
        len(bpy.context.window_manager.windows),
    )
    return (x0, y0, (x1 - x0) / 100000, (y1 - y0) / 100000), flags


def same_editor(a, b):
    """True if two editor_state() results match: the view within 2 pixels and 0.01% zoom."""
    (ax, ay, azx, azy), fa = a
    (bx, by, bzx, bzy), fb = b
    return (
        fa == fb and abs(ax - bx) <= 2 and abs(ay - by) <= 2 and abs(azx / bzx - 1) < 1e-4 and abs(azy / bzy - 1) < 1e-4
    )


def wait_capture(ui, esc_at=None):
    """Wait for the running capture to end; press Esc once tile `esc_at` is being taken."""
    for _ in range(3000):
        job = ui._CAPTURE["job"]
        if job is None:
            return
        if esc_at is not None and f"tile {esc_at}/" in job.text:
            editor()[0].event_simulate(type="ESC", value="PRESS")
            esc_at = None
        yield 0.02


def tree_state(nt):
    """Positions, logic, selection and locations of a tree (what a capture must not change)."""
    from nodefmt import api, check

    return (
        api._signature(nt),
        check.fingerprint(nt),
        {n.name: n.select for n in nt.nodes},
        {n.name: tuple(n.location) for n in nt.nodes},
    )


def capture_tests(ui):
    """Capture Tree on an example with a zone, at UI scales 1.0 and 1.4: an image of a plausible
    size made of tiles that line up, the tree, its selection and the editor as they were, no undo
    step; Esc cancels, writes nothing and puts the editor back."""
    import shutil
    import tempfile

    from nodefmt import capture

    tmp = tempfile.mkdtemp(prefix="nodefmt-test-")
    s = bpy.context.window_manager.nodefmt_capture
    s.margin, s.scope, s.clipboard, s.open_image = 40, "TREE", False, False
    name = append("NF032")
    for scale in (1.0, 1.4):
        bpy.context.preferences.view.ui_scale = scale  # in memory only
        show(name)
        yield 0.5
        nt = bpy.data.node_groups[name]
        for n in nt.nodes:
            n.select = n.name == "Group Input"
        bpy.context.window_manager.nodefmt_overlay = True
        tree, ed = tree_state(nt), editor_state()
        s.zoom = 2.0
        s.filepath = os.path.join(tmp, f"capture-{scale:g}.png")
        with override():
            r = bpy.ops.node.nodefmt_capture_tree("INVOKE_DEFAULT")
        job = ui._CAPTURE["job"]
        yield from wait_capture(ui)
        ok = r == {"RUNNING_MODAL"} and os.path.exists(s.filepath)
        w, h = capture.png_size(s.filepath) if ok else (0, 0)
        ui_s = bpy.context.preferences.system.ui_scale
        xs = [x for n in nt.nodes for x in (n.location_absolute.x, n.location_absolute.x + n.dimensions.x / ui_s)]
        ys = [y for n in nt.nodes for y in (n.location_absolute.y, n.location_absolute.y - n.dimensions.y / ui_s)]
        ew, eh = (max(xs) - min(xs)) * 2.0 + 80, (max(ys) - min(ys)) * 2.0 + 80  # nodes, zoom, margins
        extra = 2 * (capture.ZONE_EDGE + capture.BADGES) * 2.0 + 4  # zone outlines and badges
        test(
            f"capture at UI scale {scale:g}",
            ok and job.tiles > 1 and ew <= w <= ew + extra and eh <= h <= eh + extra,
            f"{w} x {h} px, expected about {ew:.0f} x {eh:.0f}, {job.tiles} tiles",
        )
        test(
            f"capture tiles line up at UI scale {scale:g}",
            job.matches and all(m is None or m <= capture.MATCH for _, _, m in job.matches),
            str([(dx, dy, None if m is None else round(m, 4)) for dx, dy, m in job.matches]),
        )
        test(f"capture keeps the tree and its selection at UI scale {scale:g}", tree_state(nt) == tree)
        test(
            f"capture puts the editor back at UI scale {scale:g}",
            same_editor(editor_state(), ed),
            f"{ed} -> {editor_state()}",
        )
    bpy.context.preferences.view.ui_scale = 1.0
    show(name)
    yield 0.5
    nt = bpy.data.node_groups[name]

    # only the selection: one node, with the margins
    for n in nt.nodes:
        n.select = n.name == "Group Input"
    s.scope, s.zoom, s.filepath = "SELECTION", 1.0, os.path.join(tmp, "selection.png")
    ed = editor_state()
    with override():
        r = bpy.ops.node.nodefmt_capture_tree("EXEC_DEFAULT")  # at once, not maximised
    w, h = capture.png_size(s.filepath) if r == {"FINISHED"} else (0, 0)
    want = nt.nodes["Group Input"].dimensions.x + 80 + 2 * capture.ZONE_EDGE
    test("capture the selection", r == {"FINISHED"} and abs(w - want) <= 4, f"{w} x {h} px, width {want:.0f} expected")
    yield 0.3
    test("capture from a script puts the editor back", same_editor(editor_state(), ed), f"{ed} -> {editor_state()}")
    s.scope = "TREE"

    # no undo step: Ctrl+Z after a capture undoes what came before it
    node = nt.nodes["Group Input"]
    old = tuple(node.location)
    with override():
        bpy.ops.ed.undo_push(message="before move")
    node.location.x += 100
    with override():
        bpy.ops.ed.undo_push(message="moved")
    s.filepath = os.path.join(tmp, "undo.png")
    with override():
        bpy.ops.node.nodefmt_capture_tree("INVOKE_DEFAULT")
    yield from wait_capture(ui)
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    nt = bpy.data.node_groups[name]
    test("capture adds no undo step", tuple(nt.nodes["Group Input"].location) == old)

    # Esc while the tiles are taken: nothing written, the editor and the tree as they were
    show(name)
    yield 0.3
    nt = bpy.data.node_groups[name]
    tree, ed = tree_state(nt), editor_state()
    s.zoom, s.filepath = 4.0, os.path.join(tmp, "esc.png")
    with override():
        bpy.ops.node.nodefmt_capture_tree("INVOKE_DEFAULT")
    job = ui._CAPTURE["job"]
    yield from wait_capture(ui, esc_at=2)
    test(
        "Esc cancels the capture",
        ui._CAPTURE["job"] is None and not os.path.exists(s.filepath) and not job.done and job.tiles > 2,
        f"{job.tiles} tiles, last {job.text!r}",
    )
    test(
        "Esc puts the editor and the tree back",
        same_editor(editor_state(), ed) and tree_state(nt) == tree,
        f"{ed} -> {editor_state()}",
    )
    shutil.rmtree(tmp, ignore_errors=True)


GEN = run()


def tick():
    """Advance the tests; quit at the end with the exit code."""
    try:
        return next(GEN)
    except StopIteration:
        pass
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
        RESULTS.append(False)
    failed = RESULTS.count(False)
    print(f"{len(RESULTS) - failed} of {len(RESULTS)} tests pass", flush=True)
    sys.stdout.flush()
    os._exit(1 if failed or not RESULTS else 0)


bpy.app.timers.register(tick, first_interval=0.5)
