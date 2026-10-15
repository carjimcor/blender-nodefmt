# SPDX-License-Identifier: GPL-3.0-or-later
"""Dump every example (examples/*.blend) as nodefmt's model data, for the layout check in CI.

    blender --factory-startup --python tools/dump_examples.py [-- OUT_DIR]

Runs with Blender's window (node sizes exist only once a tree is drawn) at UI scale 1.0 and
closes itself. Writes OUT_DIR/<example>.json (default tests/layout/trees), each {"data": model data},
the input of tools/bench.py. Then save the layout baseline the CI compares against:

    python tools/bench.py tests/layout/trees --runs 1 --save tests/layout/baseline.json
"""
import glob
import json
import os
import sys
import traceback

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = argv[0] if argv else os.path.join(ROOT, "tests", "layout", "trees")


def main():
    """Append each example's node group, read it as nodefmt does and write it as JSON."""
    from nodefmt import api
    from nodefmt.draw import Editor
    bpy.context.preferences.view.ui_scale = 1.0  # in memory only
    os.makedirs(OUT, exist_ok=True)
    ed = Editor()
    try:
        for path in sorted(glob.glob(os.path.join(ROOT, "examples", "*.blend"))):
            with bpy.data.libraries.load(path, link=False) as (src, dst):
                dst.node_groups = list(src.node_groups)
            for nt in [g for g in dst.node_groups if g is not None]:
                if nt.users > 1 or nt.bl_idname != 'GeometryNodeTree':
                    continue  # a group used inside the example's tree
                data = api.read_tree(nt, ed)
                name = os.path.splitext(os.path.basename(path))[0]
                with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8") as f:
                    json.dump({"data": data}, f, sort_keys=True, separators=(",", ":"))
                print(f"dumped {name}", flush=True)
    finally:
        ed.close()


def tick():
    """Run main() once Blender's window is up, then quit."""
    code = 0
    try:
        main()
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    os._exit(code)


bpy.app.timers.register(tick, first_interval=0.1)
