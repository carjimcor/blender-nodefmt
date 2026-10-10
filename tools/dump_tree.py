"""Read a node tree as nodefmt sees it and save it as JSON (input of tools/animate.py).

    blender file.blend --python tools/dump_tree.py -- --tree NAME --out tree.json [--ui-scale 1.4]

Runs with Blender's window (node sizes exist only once a tree is drawn) and closes itself. The
JSON holds the model data of nodefmt (node boxes, socket offsets and types, links; no socket
values), each node's colour tag and the node editor theme colours, so the schematic renderer can
draw the tree in Blender's colours.
"""
import argparse
import json
import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="dump_tree.py")
ap.add_argument("--tree", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--ui-scale", type=float, default=None)
ARGS = ap.parse_args(argv)

THEME = ("node_backdrop", "grid", "wire", "converter_node", "color_node", "group_node", "group_socket_node",
         "frame_node", "matte_node", "distor_node", "input_node", "output_node", "filter_node", "vector_node",
         "texture_node", "shader_node", "script_node", "geometry_node", "attribute_node", "simulation_zone",
         "repeat_zone", "foreach_geometry_element_zone", "closure_zone")


def main():
    from nodefmt import api
    from nodefmt.draw import Editor
    if ARGS.ui_scale:
        bpy.context.preferences.view.ui_scale = ARGS.ui_scale  # this session only, never saved
    nt = api.find_tree(ARGS.tree)
    ed = Editor()
    try:
        data = api.read_tree(nt, ed)
    finally:
        ed.close()
    th = bpy.context.preferences.themes[0].node_editor
    space = bpy.context.preferences.themes[0].node_editor.space
    theme = {k: list(getattr(th, k)) for k in THEME if hasattr(th, k)}
    theme["back"] = list(space.back)
    out = {"tree": ARGS.tree, "data": data, "theme": theme,
           "color_tag": {n.name: getattr(n, "color_tag", "NONE") for n in nt.nodes},
           "zone_type": {n.name: n.bl_idname for n in nt.nodes if hasattr(n, "paired_output")}}
    with open(ARGS.out, "w") as f:
        json.dump(out, f)
    print(f"DUMPED {ARGS.tree!r}: {len(data['nodes'])} nodes, {len(data['links'])} links, "
          f"UI scale {bpy.context.preferences.system.ui_scale:g} -> {ARGS.out}", flush=True)


def tick():
    try:
        main()
    except BaseException:
        traceback.print_exc()
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(tick, first_interval=0.3)
