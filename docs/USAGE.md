# Usage

## Install

Blender 5.2 or newer.

1. Download `nodefmt-0.8.0.zip` from the [releases](https://github.com/carjimcor/blender-nodefmt/releases),
   or build it with `tools/build.sh`.
2. In Blender: Edit > Preferences > Get Extensions > the arrow menu > Install from Disk, and pick
   `nodefmt-0.8.0.zip`. It is enabled on install.

## Supported editors

- Geometry Nodes: every node group.
- Shader: materials, worlds, lights and shader node groups.
- Compositor: the scene's compositor and compositor groups.

Zones (Repeat, Simulation, For Each Element, Closure) and frames work in every editor.

## The panel

In a node editor, open the sidebar (N) and the nodefmt tab.

- **Sort Current Tree**: sorts the tree shown in the editor.
- **Sort Selection**: sorts only the selected nodes and reroutes, or what is inside a selected
  frame; the rest of the tree stays where it is (see [below](#sort-selection)).
- **Sort All Trees**: sorts every node tree in the file (Geometry Nodes groups, materials,
  worlds, lights and the compositor). A tree that cannot be sorted without changing its logic is
  left as it was and reported.
- **Check Current Tree**: finds the rules the tree breaks, without changing it. The result
  appears in the Check section below the buttons and as marks in the editor (see
  [Check](#check)).
- **Mode**:
  - *Relayout* (default): builds a new layout from scratch: columns, order and wires.
  - *Keep layout (experimental)*: keeps your columns and order and only straightens wires and
    fixes reroutes.
- **Wires exact at UI scale**: the Resolution Scale the wires are made exact for (see
  [Limitations](LIMITATIONS.md)).
- **Check**: the result of the last check (see [Check](#check)).
- **Rules** (closed at first): one checkbox per style rule (see [Rules](RULES.md)), "Thorough
  search" (several seeds, slower, rarely better) and "Use nodefmt.toml". The same options are in
  Preferences > Add-ons > nodefmt. While "Use nodefmt.toml" is on and a `nodefmt.toml` is found
  next to the .blend file or above it, the file wins over the checkboxes and the panel shows its
  name (see [Configuration](CONFIGURATION.md)).

Each sort is one undo step: Ctrl+Z puts the tree back.

## Progress

While a sort runs, the status bar and the top of the panel show how far it is: the tree, the
pass and the step, for example "Tree 3/14 Wire: pass 1, layout 4/9 (step 6/14)", with a
progress bar. A pass reads the tree, makes copies of input nodes, lays out each container (the
tree itself, each zone and frame: "layout 4/9"), routes the wires, writes the result,
straightens it and checks the logic. Most trees take two passes: the second one finds nothing
to move.

Esc cancels the sort and puts every tree back as it was (no undo step is added). The editor
does not take other input while a sort runs.

## Sort Selection

Sort Selection sorts a part of the tree and leaves the rest alone: select some nodes and
reroutes, or a frame (everything inside it is sorted), and press the button.

- The part is laid out like a whole tree, as one block. Links coming from the rest enter the
  block on its left edge, links going to the rest leave it on its right edge.
- The block keeps the top-left corner of the part. If the sorted part is bigger and would
  overlap a node of the rest, it moves down or right (whichever is the smaller move) until it
  is clear; nothing else moves.
- The links between the part and the rest are drawn orthogonally on new reroutes: straight
  when they are level, else with one vertical run in the gap between the two ends, else around
  what is in the way. They do not pass behind nodes when a clear route exists.
- Reroutes of the part are rebuilt; selected reroutes on wires that do not touch the part are
  left alone. A frame whose nodes are all in the part moves with them.
- The selection is kept: the same nodes, plus the new reroutes.
- The logic check holds as for a whole tree, and the sort is one undo step.
- Input-like nodes are not copied (NF010): a copy would add nodes outside the selection.

| Before: the frame "Sort me" is selected | After Sort Selection |
|---|---|
| ![A tree with a messy frame selected](images/selection-before.png) | ![The frame sorted, the rest in place](images/selection-after.png) |

The tree is `examples/selection.blend`. The sorted frame is wider than before, so it moved
down to clear Mesh to Points; its links to the rest go around the nodes in the way.

## What a sort does

A sort lays the tree out left to right in columns, orders each column to remove crossings,
lines links up so that most are straight, and routes the rest as orthogonal wires on reroutes.
Besides that, with the default rules it:

- copies input-like nodes (Group Input, Named Attribute, ...) next to distant consumers (NF010);
- may swap the inputs of commutative nodes (Add, Multiply, AND, ...) to remove a crossing (NF011);
- keeps frames and zones together, and puts a self-contained frame right before the node it
  feeds (NF021);
- keeps labelled reroutes on their wires, one label at the start of each wire (NF040).

Every sort is checked against a logic fingerprint of the tree (nodes, values, links, the order
of multi-input links): if anything differs, the tree is restored and the sort reports an error.

## Check

Check runs every enabled rule on the tree as Blender draws it, and tries a sort on a copy of
the layout (undone right away): if the sort would move anything, the tree is reported as not
formatted (NF900). It changes nothing.

![The Check section of the panel and the marks in the editor](images/check-panel.png)

The Check section of the panel shows the result:

- **No problems: the tree is sorted** when nothing is broken.
- Otherwise a line on top says whether the tree is sorted ("Sorted; these style rules could not
  be met") or not ("Not sorted: Sort Current Tree fixes it"), then one row per rule broken: an
  icon (a warning for the guarantees and NF900, an info sign for style rules), the code, the
  name and how many places break it.
- **Click a rule** to select the nodes and reroutes of its next place and frame them in the
  editor (View Selected); click again for the next place, and so on around. The place shown is
  described under its row ("1/3: wire of ... runs along the edge of node ...").
- **Marks in the editor**: each place gets a ring with its rule code (red for the guarantees and
  NF900, orange for style rules; the place shown last has a bigger ring). The overlay toggle in the
  header of the Check section turns them on and off.
- The result belongs to the tree it was made for: once that tree changes, or the editor shows
  another tree, the panel asks you to check again and the marks are hidden.

A tree sorted with the same rules and UI scale reports nothing, or only style violations that
the formatter could not avoid (for example a crossing inside a bundle of wires that swap
places). NF900 and NF010 have no single place: they select and mark the nodes a sort would move
or copy. The image shows `examples/NF032.blend` after Check, with NF032 clicked.

The same check runs from the [command line](CLI.md) with `--check`; each violation is also
printed to the system console, one line each.
