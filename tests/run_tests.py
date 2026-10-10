# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests from the rule examples (examples/NF0xx.blend, built by tools/make_examples.py).

    blender --factory-startup --python tests/run_tests.py [-- --only NF031 ...]

Runs with Blender's window, like the command line (node sizes only exist once a tree is
drawn), at UI scale 1.0 (--factory-startup), and closes itself. For each example:

  check    the check reports the rule on the original tree (a guarantee, NF020 or NF022: the
           tree is reported as not formatted, NF900, since they have no geometric test)
  sort     sorting with the default rules works
  fixed    the check no longer reports the rule, a guarantee or NF900 after the sort, and no
           reroute is left leading nowhere
  logic    the logic fingerprint is the same before and after the sort
  again    a second sort changes nothing
  ignored  style rules: a fresh copy sorted with the rule ignored does not get its behaviour
           ('kept': the check still reports the rule; 'differs': the layout differs from the
           default sort; 'n/a': the example sorts the same either way)

VARIANTS run an example again after a change that real trees often have (a Group Input that
shows every socket, Blender's default). examples/selection.blend tests Sort Selection: the rest
of the tree does not move, the sorted part keeps its top-left corner (or moves just enough to
clear the rest) and overlaps nothing, its wires and its links to the rest are orthogonal and
pass behind no node, the logic is unchanged, the selection is kept (plus the new reroutes)
and a second sort changes nothing. Prints the tables and exits 1 if any test fails.
"""
import argparse
import glob
import os
import sys
import time
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="run_tests.py")
ap.add_argument("--only", action="append", default=[], help="run only this example (repeatable)")
ap.add_argument("--examples", default=os.path.join(ROOT, "examples"))
ap.add_argument("--verbose", action="store_true", help="print the violations found")
ARGS = ap.parse_args(argv)

COLUMNS = ("check", "sort", "fixed", "logic", "again", "ignored")
NOT_GEOMETRIC = ("NF005", "NF020", "NF022")  # reported as NF900 (not formatted)


def append(path):
    """The node groups of a .blend file, appended (a fresh copy every time)."""
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.node_groups = list(src.node_groups)
    return [g for g in dst.node_groups if g is not None]


def show_all_sockets(nt):
    """Show every output of the Group Input nodes (Blender's default)."""
    for n in nt.nodes:
        if n.bl_idname == 'NodeGroupInput':
            for s in n.outputs:
                s.hide = False


# example, row name, change made to the tree before the tests
VARIANTS = [("NF040", "NF040 all sockets", show_all_sockets)]


def dead_ends(nt):
    """Reroutes fed by a wire that leads nowhere (no link out)."""
    return sum(1 for n in nt.nodes if n.bl_idname == 'NodeReroute'
               and n.inputs[0].is_linked and not n.outputs[0].is_linked)


def codes(vs):
    """The rule codes of a list of violations."""
    return {v.code for v in vs}


def zone_offset(nt):
    """Height of the first zone output's top above its zone input's top (0: level)."""
    for n in nt.nodes:
        out = getattr(n, "paired_output", None)
        if out is not None:
            return round(out.location_absolute.y - n.location_absolute.y, 1)
    return None


def feeds(nt, node_type, out_index, to_type):
    """Index of the input of the first `to_type` node that output `out_index` of the first
    `node_type` node reaches (through reroutes), or None."""
    src = next(n for n in nt.nodes if n.bl_idname == node_type)
    todo = list(src.outputs[out_index].links)
    while todo:
        l = todo.pop()
        if l.to_node.bl_idname == 'NodeReroute':
            todo += list(l.to_node.outputs[0].links)
        elif l.to_node.bl_idname == to_type:
            return list(l.to_node.inputs).index(l.to_socket)
    return None


# observable effect of a style rule: (what to measure, the value with the rule, without it)
EFFECT = {
    "NF010": ("Group Input nodes", lambda nt: sum(n.bl_idname == 'NodeGroupInput' for n in nt.nodes)),
    "NF011": ("input fed by X", lambda nt: feeds(nt, 'ShaderNodeSeparateXYZ', 0, 'ShaderNodeMath')),
    "NF020": ("zone output above input", zone_offset),
}


def run_one(path, ed, prepare=None):
    """The results of one example: {column: (ok or None, text)}. prepare(tree) changes the
    tree first (a variant)."""
    from nodefmt import api, check, rules
    code = os.path.splitext(os.path.basename(path))[0]
    out = {}
    nt = append(path)[0]
    if prepare:
        prepare(nt)
    dead = dead_ends(nt)
    cfg = rules.Config()
    vs = api.check_tree(nt, 'relayout', ed, cfg)
    found = codes(vs)
    want = 'NF900' if code in NOT_GEOMETRIC else code
    out["check"] = (want in found and (code not in rules.GUARANTEES or 'NF900' in found),
                    ", ".join(sorted(found)) or "nothing")
    if ARGS.verbose:
        for v in vs:
            print(f"  {code} before: {v.code} {v.msg} at ({v.x:g}, {v.y:g})", flush=True)
    fp = check.fingerprint(nt)
    try:
        st = api.format_tree(nt, 'relayout', ed, cfg=cfg)
        out["sort"] = (True, f"{st['seconds']} s")
    except api.LogicChanged as e:
        out["sort"] = (False, str(e))
        return out
    d = check.diff(fp, check.fingerprint(nt))
    out["logic"] = (not d, "same" if not d else "; ".join(d[:2]))
    vs = api.check_tree(nt, 'relayout', ed, cfg)
    left = codes(vs)
    bad = left & ({code, 'NF900'} | set(rules.GUARANTEES))
    loose = dead_ends(nt) - dead
    text = ", ".join(sorted(left)) or "clean"
    out["fixed"] = (not bad and loose <= 0, text + (f"; {loose} reroutes lead nowhere" if loose > 0 else ""))
    if ARGS.verbose:
        for v in vs:
            print(f"  {code} after: {v.code} {v.msg} at ({v.x:g}, {v.y:g})", flush=True)
    ed.show(nt)
    sig = api._signature(nt)
    api.format_tree(nt, 'relayout', ed, cfg=cfg)
    ed.show(nt)
    out["again"] = (api.same_layout(api._signature(nt), sig), "")
    if code in rules.STYLE:
        off = append(path)[0]
        if prepare:
            prepare(off)
        api.format_tree(off, 'relayout', ed, cfg=rules.Config(rules.resolve(None, [code])))
        ed.show(off)
        if code in EFFECT:
            what, measure = EFFECT[code]
            on_v, off_v = measure(nt), measure(off)
            out["ignored"] = (on_v != off_v, f"{what}: {on_v} with the rule, {off_v} without")
        else:
            kept = code in codes(api.check_tree(off, 'relayout', ed, cfg, formatted=False))
            differs = not api.same_layout(api._signature(off), api._signature(nt))
            out["ignored"] = (None, "kept" if kept else "differs" if differs else "n/a")
        bpy.data.node_groups.remove(off)
    else:
        out["ignored"] = (None, "guarantee")
    bpy.data.node_groups.remove(nt)
    return out


# ---------------------------------------------------------------- Sort Selection
SEL_COLUMNS = ("rest", "anchored", "overlap", "wires", "logic", "kept", "again")
# scenario, nodes to select (None: as saved, the frame "Sort me")
SCENARIOS = [("frame", None), ("two nodes", ["Group Input", "Set Position"]),
             ("split", ["Transform Geometry", "Triangulate Mesh"])]


def link_faults(nt, names):
    """(segments not orthogonal, segments behind a node) of the drawn links that touch the nodes
    `names`."""
    from nodefmt import ortho, wires
    ui = bpy.context.preferences.system.ui_scale
    boxes = {}
    for n in nt.nodes:
        if n.bl_idname not in ('NodeFrame', 'NodeReroute'):
            x, y = n.location_absolute
            boxes[n.name] = (x, -y, x + n.dimensions.x / ui, -y + n.dimensions.y / ui)
    bent = behind = 0
    for l, a, b in ortho.drawn(nt):
        if l.from_node.name not in names and l.to_node.name not in names:
            continue
        bent += ortho.bad(a, b)
        seg = (None, (a[0], -a[1]), (b[0], -b[1]))
        behind += any(wires.behind(seg, box) for k, box in boxes.items() if k not in (l.from_node.name, l.to_node.name))
    return bent, behind


def run_selection(path, ed, names):
    """The results of one Sort Selection scenario: {column: (ok, text)}."""
    from nodefmt import api, check, part
    nt = append(path)[0]
    if names is not None:
        for n in nt.nodes:
            n.select = n.name in names
    ed.show(nt)
    ui = bpy.context.preferences.system.ui_scale
    real, rr, frames = part.selection(nt)
    rest = {n.name: tuple(n.location_absolute) for n in nt.nodes
            if n.name not in real | rr | frames and n.bl_idname != 'NodeFrame'}
    selected = {n.name for n in nt.nodes if n.select}
    old_names = {n.name for n in nt.nodes}
    fp = check.fingerprint(nt)
    out = {}
    st = part.sort_selection(nt, ed)
    ed.show(nt)
    moved = [k for k, p in rest.items() if k not in nt.nodes or tuple(nt.nodes[k].location_absolute) != p]
    out["rest"] = (not moved, f"{len(moved)} moved" if moved else f"{len(rest)} in place")
    box, old = st["box"], st["old"]
    if any(st["moved"]):
        out["anchored"] = (True, f"moved {st['moved']} to clear the rest")
    else:
        d = (abs(box[0] - old[0]), abs(box[3] - old[3]))
        out["anchored"] = (max(d) <= 1.0, f"top-left off by {d[0]:g}, {d[1]:g}")
    boxes = {n.name: part._box(n, ui) for n in nt.nodes if n.bl_idname not in ('NodeFrame', 'NodeReroute')}
    hits = [(a, b) for a in real for b in rest if b in boxes and part._overlaps(boxes[a], boxes[b])]
    out["overlap"] = (not hits, f"{hits[:2]}" if hits else "none")
    new = {n.name for n in nt.nodes if n.name not in old_names}
    bent, behind = link_faults(nt, real | rr | new)
    out["wires"] = (not bent and not behind, f"{bent} not orthogonal, {behind} behind nodes")
    d = check.diff(fp, check.fingerprint(nt))
    out["logic"] = (not d, "same" if not d else "; ".join(d[:2]))
    now = {n.name for n in nt.nodes if n.select}
    want = {k for k in selected if k in nt.nodes} | new
    out["kept"] = (now == want, f"{len(now)} selected")
    sig = api._signature(nt)
    part.sort_selection(nt, ed)
    ed.show(nt)
    out["again"] = (api.same_layout(api._signature(nt), sig), "")
    bpy.data.node_groups.remove(nt)
    return out


def main():
    """Run every example and print the table; returns the exit code."""
    from nodefmt.draw import Editor
    bpy.context.preferences.view.ui_scale = 1.0  # in memory only
    files = sorted(glob.glob(os.path.join(ARGS.examples, "NF*.blend")))
    if ARGS.only:
        files = [f for f in files if os.path.splitext(os.path.basename(f))[0] in ARGS.only]
    if not files and "selection" not in ARGS.only:
        print("run_tests: no examples found", flush=True)
        return 1
    runs = [(os.path.splitext(os.path.basename(f))[0], f, None) for f in files]
    by_code = {r[0]: r[1] for r in runs}
    runs += [(name, by_code[code], prep) for code, name, prep in VARIANTS if code in by_code]
    rows, failed = [], 0
    t0 = time.perf_counter()
    ed = Editor()
    try:
        for code, path, prep in runs:
            try:
                res = run_one(path, ed, prep)
            except Exception as e:
                traceback.print_exc()
                res = {"sort": (False, f"error: {e}")}
            rows.append((code, res))
            bad = [c for c in COLUMNS if res.get(c, (None,))[0] is False]
            failed += bool(bad)
            print(f"{code}: {'FAIL ' + ', '.join(bad) if bad else 'ok'}", flush=True)
    finally:
        ed.close()
    print()
    print("| Rule | " + " | ".join(COLUMNS) + " |")
    print("|---" * (len(COLUMNS) + 1) + "|")
    for code, res in rows:
        cells = []
        for c in COLUMNS:
            ok, text = res.get(c, (False, "not run"))
            mark = "ok" if ok else "FAIL" if ok is False else ""
            cells.append(" ".join(x for x in (mark, f"({text})" if text and ok is not None else text) if x))
        print(f"| {code} | " + " | ".join(cells) + " |")
    print(f"\n{len(rows) - failed} of {len(rows)} examples pass ({time.perf_counter() - t0:.1f} s)", flush=True)
    sel = os.path.join(ARGS.examples, "selection.blend")
    if os.path.exists(sel) and (not ARGS.only or "selection" in ARGS.only):
        print("\n| Sort Selection | " + " | ".join(SEL_COLUMNS) + " |")
        print("|---" * (len(SEL_COLUMNS) + 1) + "|")
        ed = Editor()
        try:
            for name, nodes in SCENARIOS:
                try:
                    res = run_selection(sel, ed, nodes)
                except Exception as e:
                    traceback.print_exc()
                    res = {"rest": (False, f"error: {e}")}
                bad = [c for c in SEL_COLUMNS if res.get(c, (False,))[0] is False]
                failed += bool(bad)
                cells = [("ok" if res[c][0] else "FAIL") + (f" ({res[c][1]})" if res[c][1] else "")
                         if c in res else "not run" for c in SEL_COLUMNS]
                print(f"| {name} | " + " | ".join(cells) + " |", flush=True)
        finally:
            ed.close()
    return 1 if failed else 0


def tick():
    """Run main() once Blender's window is up, then quit with its exit code."""
    try:
        code = main()
    except BaseException:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
