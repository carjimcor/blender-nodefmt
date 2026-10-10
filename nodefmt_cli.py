# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line for nodefmt (for a git pre-commit hook), in the style of ruff.

  blender file.blend --python nodefmt_cli.py -- --check [options]
  blender file.blend --python nodefmt_cli.py -- --fix   [options]

Options:
  --select CODES     rules to apply and check (comma-separated codes, prefixes or names; default ALL)
  --ignore CODES     rules to switch off (added to the config file's ignore list)
  --thorough         search with several seeds (slower; the default is one deterministic pass)
  --config PATH      a nodefmt.toml to use (default: the first one found from the .blend's folder up)
  --ui-scale S       the Resolution Scale to format for (default: Blender's, or the config's)
  --tree NAME        only this tree (repeatable): a group name or "Material: <name>", ...
  --no-format-check  --check: report rule violations only, without trying a format (NF900)
  --statistics       print the number of violations per rule
  --strict           --check: fail on any violation (default: only on NF900 and the guarantees)
  --list-rules       print the rules and exit

Each tree gets a progress line "[3/14] sorting NAME"; on a terminal, --fix also shows the steps
of the sort on one line ("pass 1 (of at most 6), layout 4/9 (step 6/14)").

--check changes nothing and prints one line per violation with its rule code, as ruff does. It
exits 1 if a tree is not formatted (NF900) or breaks a guarantee (NF001-NF005); a style rule
that a formatted tree still breaks (the formatter could not do better, for example a crossing
inside a bundle) is reported but fails the check only with --strict. --fix formats and
saves the file, prints what is left, and exits 2 if a tree could not be formatted without
changing its logic (that tree is left as it was). Blender must run with its window (not -b):
node sizes and socket positions only exist after Blender draws a tree.

Wires are exactly orthogonal at the UI scale the tree is formatted at (see ortho.py). Run without
--factory-startup so Blender uses your preferences (your Resolution Scale), or give the scale with
--ui-scale or ui-scale in nodefmt.toml (set for this run only; preferences are never saved).
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
ap.add_argument("--mode", choices=["relayout", "keep"], default="relayout")
ap.add_argument("--tree", action="append", default=[])
ap.add_argument("--ui-scale", type=float, default=None)
ap.add_argument("--select", default=None)
ap.add_argument("--ignore", default=None)
ap.add_argument("--thorough", action="store_true", default=None)
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
    cfg = rules.load(start, _codes(ARGS.select), _codes(ARGS.ignore), thorough=ARGS.thorough, ui_scale=ARGS.ui_scale)
    if ARGS.config and os.path.abspath(cfg.source or "") != os.path.abspath(ARGS.config):
        raise SystemExit(f"nodefmt: config {ARGS.config} not found or not readable")
    return cfg


def sort(api, nt, cfg, ed, prefix):
    """Sort one tree (api.format_steps). On a terminal the steps are shown on one line that is
    overwritten as the sort goes on."""
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


def main():
    """Check or format the trees; returns the exit code."""
    from nodefmt import api, lint, rules
    from nodefmt.draw import Editor
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
          f"{'thorough' if cfg.thorough else 'one pass'}; config: {cfg.source or 'none'}", flush=True)
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
    except BaseException:
        traceback.print_exc()
        code = 3
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
