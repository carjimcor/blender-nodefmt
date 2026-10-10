# Usage

## Install

Blender 5.2 or newer.

1. Download `nodefmt-0.7.0.zip` from the [releases](https://github.com/carjimcor/blender-nodefmt/releases),
   or build it with `tools/build.sh`.
2. In Blender: Edit > Preferences > Get Extensions > the arrow menu > Install from Disk, and pick
   `nodefmt-0.7.0.zip`. It is enabled on install.

## Supported editors

- Geometry Nodes: every node group.
- Shader: materials, worlds, lights and shader node groups.
- Compositor: the scene's compositor and compositor groups.

Zones (Repeat, Simulation, For Each Element, Closure) and frames work in every editor.

## The panel

In a node editor, open the sidebar (N) and the nodefmt tab.

- **Sort Current Tree**: sorts the tree shown in the editor.
- **Sort All Trees**: sorts every node tree in the file (Geometry Nodes groups, materials,
  worlds, lights and the compositor). A tree that cannot be sorted without changing its logic is
  left as it was and reported.
- **Check Current Tree**: reports which rules the tree breaks, with their codes, without
  changing it. Use it on a tree you edited by hand; the result appears in the panel and, line by
  line, in the system console.
- **Mode**:
  - *Relayout* (default): builds a new layout from scratch: columns, order and wires.
  - *Keep layout (experimental)*: keeps your columns and order and only straightens wires and
    fixes reroutes.
- **UI scale**: the panel shows the Resolution Scale the wires are made exact for (see
  [Limitations](LIMITATIONS.md)).
- **Rules**: one checkbox per style rule (see [Rules](RULES.md)), "Thorough search" (several
  seeds, slower, rarely better) and "Use nodefmt.toml". The same options are in Preferences >
  Add-ons > nodefmt. While "Use nodefmt.toml" is on and a `nodefmt.toml` is found next to the
  .blend file or above it, the file wins over the checkboxes and the panel shows its name (see
  [Configuration](CONFIGURATION.md)).

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
formatted (NF900). A tree that was sorted with the same rules and UI scale reports nothing, or
only style violations that the formatter could not avoid (for example a crossing inside a
bundle of wires that swap places).

The same check runs from the [command line](CLI.md) with `--check`.
