#!/bin/sh
# Rebuild the demo animation in media/ from a node tree of a .blend file.
#   tools/make_demo.sh file.blend "Tree name" [seed]
# BLENDER: the Blender executable (default "blender"); PYTHON: a Python with Pillow, numpy and
# PyAV (default "python"). The .blend is opened, never saved; scratch files go to a temp folder.
# The README demo uses a Geometry Nodes group named "Wire", seed 3, with every rule on.
set -e
cd "$(dirname "$0")/.."
BLENDER=${BLENDER:-blender}
PYTHON=${PYTHON:-python}
blend=$1
tree=$2
seed=${3:-3}
tmp=$(mktemp -d)
"$BLENDER" "$blend" --no-window-focus --python tools/scramble.py -- --tree "$tree" --seed "$seed" --ui-scale 1.4 --out "$tmp/messy.blend"
"$BLENDER" "$tmp/messy.blend" --no-window-focus --python tools/dump_tree.py -- --tree "$tree" --ui-scale 1.4 --out "$tmp/tree.json"
BLENDER_DIR=$(dirname "$(command -v "$BLENDER")") "$PYTHON" tools/animate.py "$tmp/tree.json" media --select ALL
echo "messy tree kept in $tmp/messy.blend"
