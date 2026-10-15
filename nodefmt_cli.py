# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line for nodefmt (for a git pre-commit hook), in the style of ruff.

  blender file.blend --python nodefmt_cli.py -- --check [options]
  blender file.blend --python nodefmt_cli.py -- --fix   [options]
  blender file.blend --python nodefmt_cli.py -- --capture TREE [--out FILE.png] [--zoom 1.0]

Options:
  --select CODES     rules to apply and check (comma-separated codes, prefixes, names or ALL;
                     default: the config's, else all but the opt-in rules NF022, NF023, NF035)
  --ignore CODES     rules to switch off (added to the config file's ignore list)
  --config PATH      a nodefmt.toml to use (default: the first one found from the .blend's folder up)
  --ui-scale S       the Resolution Scale to format for (default: the config's, else Blender's)
  --tree NAME        only this tree (repeatable): a group name or "Material: <name>", ...
  --mode M           relayout (default) or keep (start from the current layout)
  --no-format-check  --check: report rule violations only, without trying a format (NF900)
  --statistics       print the number of violations per rule
  --strict           --check: fail on any violation (default: only on NF900 and the guarantees)
  --list-rules       print the rules and exit
  --capture TREE     save an image of tree TREE (see --tree for names) and exit; changes nothing
  --out PATH         --capture: the PNG file, or a folder (default: a 'captures' folder next to
                     the .blend file)
  --zoom Z           --capture: screen pixels per node unit (default 1.0)
  --margin PX        --capture: empty pixels around the tree (default 40)

--check changes nothing and prints one line per violation with its rule code. It exits 1 if a
tree is not formatted (NF900) or breaks a guarantee (NF001-NF005); a style rule that a formatted
tree still breaks (the formatter could not do better) fails the check only with --strict.
--fix formats and saves the file, prints what is left, and exits 2 if a tree could not be
formatted without changing its logic (that tree is left as it was). Errors exit 3. Each tree
gets a progress line; on a terminal --fix also shows the steps of the sort.

Blender must run with its window (not -b): node sizes and socket positions only exist once a
tree is drawn. Wires are exactly orthogonal only at the UI scale the tree is formatted at: run
without --factory-startup to use your Resolution Scale, or set it with --ui-scale or ui-scale in
nodefmt.toml (for this run only; preferences are never saved).
"""
import argparse
import os
import sys
import time
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="nodefmt_cli.py")
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--check", action="store_true")
g.add_argument("--fix", action="store_true")
g.add_argument("--list-rules", action="store_true")
g.add_argument("--capture", metavar="TREE", default=None)
ap.add_argument("--out", default="")
ap.add_argument("--zoom", type=float, default=1.0)
ap.add_argument("--margin", type=int, default=40)
ap.add_argument("--mode", choices=["relayout", "keep"], default="relayout")
ap.add_argument("--tree", action="append", default=[])
ap.add_argument("--ui-scale", type=float, default=None)
ap.add_argument("--select", default=None)
ap.add_argument("--ignore", default=None)
ap.add_argument("--config", default=None)
ap.add_argument("--no-format-check", action="store_true")
ap.add_argument("--statistics", action="store_true")
ap.add_argument("--strict", action="store_true")
ARGS = ap.parse_args(argv)


def _codes(text):
    """A comma-separated list of codes as a list (None if not given)."""
    return [c.strip() for c in text.split(",") if c.strip()] if text else None


def config():
    """The run's rules.Config: the config file, then the command line on top."""
    from nodefmt import rules
    start = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
    if ARGS.config:
        start = os.path.dirname(os.path.abspath(ARGS.config))
    cfg = rules.load(start, _codes(ARGS.select), _codes(ARGS.ignore), ui_scale=ARGS.ui_scale)
    if ARGS.config and os.path.abspath(cfg.source or "") != os.path.abspath(ARGS.config):
        raise SystemExit(f"nodefmt: config {ARGS.config} not found or not readable")
    return cfg


def sort(api, nt, cfg, ed, prefix):
    """Sort one tree (api.format_steps), showing its steps on one overwritten line on a terminal."""
    tty = sys.stdout.isatty()
    gen = api.format_steps(nt, ARGS.mode, ed, cfg=cfg)
    width = 0
    try:
        while True:
            try:
                st = next(gen)
            except StopIteration as e:
                return e.value
            if tty:
                line = prefix + st.text()
                print("\r" + line.ljust(width), end="", flush=True)
                width = len(line)
    finally:
        if tty and width:
            print("\r" + " " * width + "\r", end="", flush=True)


def capture_main():
    """Save an image of one tree (--capture); returns the exit code."""
    from nodefmt import api, capture
    from nodefmt.draw import Editor
    prefs = bpy.context.preferences
    old_scale = prefs.view.ui_scale
    if ARGS.ui_scale:
        prefs.view.ui_scale = ARGS.ui_scale
    ed = None
    try:
        nt = api.find_tree(ARGS.capture)
        ed = Editor()  # a node editor of the window, or its largest area turned into one
        ed.show(nt)
        out = os.path.abspath(ARGS.out) if ARGS.out else ""
        job = capture.CaptureJob(ed.win, ed.area, capture.Options(zoom=ARGS.zoom, margin=ARGS.margin, path=out))
        job.run()
    except (KeyError, capture.CaptureError) as e:
        print(f"nodefmt: cannot capture {ARGS.capture}: {e.args[0]}", flush=True)
        return 3
    finally:
        if ed is not None:
            ed.close()
        prefs.view.ui_scale = old_scale
    for w in job.warnings:
        print(f"warning: {w}", flush=True)
    print(f"nodefmt: {job.report()}", flush=True)
    return 0


def main():
    """Check or format the trees, or capture one; returns the exit code."""
    from nodefmt import api, lint, rules
    from nodefmt.draw import Editor
    if ARGS.capture:
        return capture_main()
    if ARGS.list_rules:
        for code, name, kind, summary in rules.RULES:
            print(f"{code} {name} ({kind}): {summary}")
        return 0
    t0 = time.perf_counter()
    cfg = config()
    prefs = bpy.context.preferences
    old_scale = prefs.view.ui_scale
    if cfg.ui_scale:
        prefs.view.ui_scale = cfg.ui_scale
    trees = [api.find_tree(n) for n in ARGS.tree] if ARGS.tree else api.all_trees()
    # tree edits re-evaluate modifiers; switch them off meanwhile (restored before saving)
    mods = [(m, m.show_viewport) for o in bpy.data.objects for m in o.modifiers if m.type == 'NODES']
    for m, _ in mods:
        m.show_viewport = False
    ed = Editor()
    ed.redraw()
    off = [c for c in rules.STYLE if not cfg.on(c)]
    print(f"nodefmt: UI scale {prefs.system.ui_scale:g}; rules off: {', '.join(off) or 'none'}; "
          f"config: {cfg.source or 'none'}", flush=True)
    code = 0
    found, bad_trees = [], 0
    name = os.path.basename(bpy.data.filepath) or "untitled"
    try:
        for k, nt in enumerate(trees, 1):
            what = "sorting" if ARGS.fix else "checking"
            print(f"[{k}/{len(trees)}] {what} {api.tree_name(nt)}", flush=True)
            if ARGS.fix:
                try:
                    st = sort(api, nt, cfg, ed, f"[{k}/{len(trees)}] {api.tree_name(nt)}: ")
                    print(f"formatted {api.tree_name(nt)} ({st['seconds']} s)", flush=True)
                except api.LogicChanged as e:
                    print(f"SKIPPED {e}", flush=True)
                    code = 2
            vs = api.check_tree(nt, ARGS.mode, ed, cfg, formatted=ARGS.check and not ARGS.no_format_check)
            for line in lint.report(vs, f"{name}: {api.tree_name(nt)}: "):
                print(line, flush=True)
            found += vs
            bad_trees += bool(vs)
    finally:
        ed.close()
        for m, v in mods:
            m.show_viewport = v
        prefs.view.ui_scale = old_scale
    if ARGS.statistics and found:
        for c, n in lint.counts(found).items():
            print(f"{n:5d}  {c}  {rules.NAMES.get(c, 'not-formatted')}")
    if ARGS.fix:
        bpy.ops.wm.save_mainfile()
        print(f"nodefmt: {len(trees)} trees formatted in {time.perf_counter() - t0:.2f} s; "
              f"{len(found)} violations left in {bad_trees} trees", flush=True)
    else:
        print(f"nodefmt: {len(found)} violations in {bad_trees} of {len(trees)} trees "
              f"({time.perf_counter() - t0:.2f} s)", flush=True)
        failing = [v for v in found if ARGS.strict or v.code == 'NF900' or v.code in rules.GUARANTEES]
        code = 1 if failing else 0
    return code


def tick():
    """Run main() once Blender's window is up, then quit with its exit code."""
    try:
        code = main()
    except SystemExit as e:
        print(e, flush=True)
        code = 3
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
        code = 3
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
