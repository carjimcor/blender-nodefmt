# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the add-on operators: sorting with progress, Esc, undo, Sort Selection.

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
EXAMPLES = ("NF010", "NF021", "NF030")
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
    area = next((a for a in win.screen.areas if a.type == 'NODE_EDITOR'), None)
    if area is None:
        area = max(win.screen.areas, key=lambda a: a.width * a.height)
        area.ui_type = 'GeometryNodeTree'
    return win, area, next(r for r in area.regions if r.type == 'WINDOW')


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
            editor()[0].event_simulate(type='ESC', value='PRESS')
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
    show(names[1])  # NF021: a frame, so the layout has two containers
    yield 0.3
    with override():
        bpy.ops.ed.undo_push(message="test start")
    start = state(names)

    # Sort Current Tree with progress, then one undo step
    seen = []
    with override():
        r = bpy.ops.node.nodefmt_sort_tree('INVOKE_DEFAULT', True)
    test("sort current tree starts", r == {'RUNNING_MODAL'}, str(r))
    yield from wait_job(ui, seen)
    after = state(names)
    test("sort current tree sorts", after[names[1]][0] != start[names[1]][0] and after[names[0]] == start[names[0]])
    test("logic unchanged", after[names[1]][1] == start[names[1]][1])
    texts = [t for t, _ in seen]
    pattern = re.compile(r"Tree 1/1 .+: pass \d+, .+ \(step \d+/\d+\)$")
    test("progress shown", len(seen) >= 3 and all(pattern.match(t) for t in texts[1:]),
         f"{len(seen)} updates, e.g. {texts[len(texts) // 2]!r}")
    factors = [f for _, f in seen]
    test("progress never goes back", factors == sorted(factors), f"{factors[0]:.2f} .. {factors[-1]:.2f}")
    test("layout steps counted", any(re.search(r"layout \d+/\d+", t) for t in texts))
    test("status bar cleared", ui._JOB["job"] is None)
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    test("one undo step puts the tree back", state(names) == start)

    # Sort All Trees, cancelled with Esc after a few steps: everything is put back
    seen = []
    with override():
        r = bpy.ops.node.nodefmt_sort_all('INVOKE_DEFAULT', True)
    test("sort all starts", r == {'RUNNING_MODAL'}, str(r))
    yield from wait_job(ui, seen, press_esc_after=8)
    test("Esc cancels", ui._JOB["job"] is None and len(seen) >= 8, f"{len(seen)} updates, last {seen[-1][0]!r}")
    test("Esc puts every tree back", state(names) == start)

    # Sort All Trees to the end, then undo
    seen = []
    with override():
        r = bpy.ops.node.nodefmt_sort_all('INVOKE_DEFAULT', True)
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
        r = bpy.ops.node.nodefmt_sort_selection('INVOKE_DEFAULT', True)
    yield 0.3
    test("sort selection", r == {'FINISHED'} and state([sel])[sel][0] != before[sel][0], str(r))
    test("sort selection keeps the logic", state([sel])[sel][1] == before[sel][1])
    with override():
        bpy.ops.ed.undo()
    yield 0.3
    test("one undo step puts the selection back", state([sel]) == before)

    # scripts: EXEC_DEFAULT sorts at once
    with override():
        r = bpy.ops.node.nodefmt_sort_all('EXEC_DEFAULT', True)
    test("sort all from a script", r == {'FINISHED'} and state(names) != start, str(r))
    ui.unregister()


GEN = run()


def tick():
    """Advance the tests; quit at the end with the exit code."""
    try:
        return next(GEN)
    except StopIteration:
        pass
    except BaseException:
        traceback.print_exc()
        RESULTS.append(False)
    failed = RESULTS.count(False)
    print(f"{len(RESULTS) - failed} of {len(RESULTS)} tests pass", flush=True)
    sys.stdout.flush()
    os._exit(1 if failed or not RESULTS else 0)


bpy.app.timers.register(tick, first_interval=0.5)
