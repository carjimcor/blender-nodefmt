"""Make a messy, reproducible copy of a node tree (the start of the demo animation).

    blender file.blend --python tools/scramble.py -- --tree NAME --out messy.blend [--seed 7] [--ui-scale 1.4]

Runs with Blender's window (node sizes exist only once a tree is drawn) and closes itself. Every
reroute is removed (links go directly to their real source), each node gets a longest-path
column so data still flows left to right, and each column is stacked in a random order with
random gaps and x jitter. The copy is saved only if the logic fingerprint (nodefmt.check) is
unchanged. --blank-label LABEL (repeatable) empties the String nodes with that label in the copy
(to keep private text out of the demo).
"""
import argparse
import os
import random
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser(prog="scramble.py")
ap.add_argument("--tree", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--blank-label", action="append", default=[], metavar="LABEL")
ap.add_argument("--seed", type=int, default=7)
ap.add_argument("--ui-scale", type=float, default=None)
ARGS = ap.parse_args(argv)

REROUTE = 'NodeReroute'


def real_source(sock):
    """The output socket that feeds `sock` through any chain of reroutes (None if dangling)."""
    while sock.node.bl_idname == REROUTE:
        links = sock.node.inputs[0].links
        if not links:
            return None
        sock = links[0].from_socket
    return sock


def remove_reroutes(nt):
    """Link every input directly to its real source and delete all reroutes."""
    for n in list(nt.nodes):
        if n.bl_idname == REROUTE:
            continue
        for s in n.inputs:
            links = sorted(s.links, key=lambda l: l.multi_input_sort_id)
            if not any(l.from_node.bl_idname == REROUTE for l in links):
                continue
            srcs = [real_source(l.from_socket) for l in links]
            for l in links:
                nt.links.remove(l)
            for src in srcs:  # in their old order (a multi-input socket keeps it)
                if src is not None:
                    nt.links.new(src, s)
    for n in [n for n in nt.nodes if n.bl_idname == REROUTE]:
        nt.nodes.remove(n)


def columns(nt):
    """Longest-path column of every node that is not a frame (empty columns removed)."""
    nodes = [n for n in nt.nodes if n.bl_idname != 'NodeFrame']
    preds = {n.name: set() for n in nodes}
    for l in nt.links:
        if l.from_node.name in preds and l.to_node.name in preds and not l.is_hidden:
            preds[l.to_node.name].add(l.from_node.name)
    col = {}

    def depth(name, seen=()):
        """Column of node `name`: one more than its deepest source."""
        if name not in col:
            col[name] = 1 + max((depth(p, seen + (name,)) for p in preds[name] if p not in seen), default=-1)
        return col[name]
    for n in nodes:
        depth(n.name)
    # a node with nothing linked in sits right before its first consumer, as people place them
    for n in nodes:
        succ = [l.to_node.name for l in nt.links if l.from_node.name == n.name and l.to_node.name in col]
        if not preds[n.name] and succ:
            col[n.name] = max(0, min(col[m] for m in succ) - 1)
    used = sorted(set(col.values()))  # no empty columns
    return {n: used.index(c) for n, c in col.items()}


def scramble(nt, rng, boxes):
    """New locations: topological columns, random order, gaps and jitter."""
    col = columns(nt)
    size = {n: (boxes[n]["w"], boxes[n]["h"]) for n in col}
    ncols = max(col.values()) + 1
    x, xs = 0.0, []
    for c in range(ncols):
        xs.append(x)
        x += max(size[n][0] for n in col if col[n] == c) + rng.uniform(70, 150)
    for c in range(ncols):
        names = sorted(n for n in col if col[n] == c)
        rng.shuffle(names)
        y = rng.uniform(-300, 200)
        for name in names:
            node = nt.nodes[name]
            framed = node.parent is not None
            y -= 45 if framed else 0  # room for the frame's label
            node.location_absolute = (round(xs[c] + rng.uniform(-30, 30)), round(y))
            y -= size[name][1] + rng.uniform(30, 140) + (35 if framed else 0)


def main():
    """Scramble the tree, check its logic is unchanged and save a copy of the file."""
    from nodefmt import api, check
    from nodefmt.draw import Editor
    if ARGS.ui_scale:
        bpy.context.preferences.view.ui_scale = ARGS.ui_scale  # this session only, never saved
    nt = bpy.data.node_groups[ARGS.tree]
    before = check.fingerprint(nt)
    remove_reroutes(nt)
    ed = Editor()
    boxes = api.read_tree(nt, ed)["nodes"]  # node sizes as nodefmt measures them
    scramble(nt, random.Random(ARGS.seed), boxes)
    ed.close()
    diff = check.diff(before, check.fingerprint(nt))
    if diff:
        print("SCRAMBLE FAILED: logic changed:", diff[:5], flush=True)
        return
    blanked = 0
    for tree in bpy.data.node_groups:
        for n in tree.nodes:
            if n.bl_idname == 'FunctionNodeInputString' and n.label in ARGS.blank_label:
                n.string = ""
                blanked += 1
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(ARGS.out), copy=True)
    print(f"SCRAMBLED {ARGS.tree!r} seed {ARGS.seed}: {len(nt.nodes)} nodes, {len(nt.links)} links, "
          f"{blanked} String nodes emptied -> {ARGS.out}", flush=True)


def tick():
    """Run main() once Blender's window is up, then quit."""
    try:
        main()
    except BaseException:  # noqa: BLE001 - any error must still quit Blender
        traceback.print_exc()
    sys.stdout.flush()
    os._exit(0)


bpy.app.timers.register(tick, first_interval=0.3)
