# nodefmt

A formatter for Blender node trees, in the spirit of code formatters such as ruff or black. It
sorts a tree into columns, orders the nodes to remove crossings, lines links up and routes the
rest as orthogonal wires on reroutes. It never changes what the tree computes, and sorting a
sorted tree changes nothing.

<p align="center"><img src="media/nodefmt-demo.webp" alt="A messy node tree being sorted step by step: links become direct lines, nodes slide into columns, columns are reordered, heights settle and orthogonal wires are drawn" width="960"></p>

The animation shows the steps on a messy tree ([MP4](media/nodefmt-demo.mp4),
[GIF](media/nodefmt-demo.gif)). The same tree in Blender, before and after:
[media/before-after.png](media/before-after.png). The tree is the "Wire" group from
[aoc-2015-blender-gn](https://github.com/carjimcor/aoc-2015-blender-gn), Advent of Code 2015
solved with Geometry Nodes, the project nodefmt was made for.

## What it guarantees

- **Logic never changes.** Each sort compares a logic fingerprint of the tree (nodes, values,
  links, the order of multi-input links) before and after, and restores the tree if anything
  differs.
- **No curved wires.** A link that is not straight turns at right angles on reroutes.
- **Nothing behind nodes.** No wire passes behind a node.
- **Orthogonal at your UI scale.** Every drawn segment is exactly horizontal or vertical at the
  Resolution Scale you work at.
- **Idempotent and deterministic.** The same tree always gives the same layout, and a sorted tree
  stays as it is.

It also copies input-like nodes (Group Input, Named Attribute, ...) next to distant consumers,
may swap the inputs of commutative nodes (Add, Multiply, AND, ...) to remove a crossing, keeps
frames and zones together and keeps labelled reroutes on their wires.

## Install

Blender 5.2 or newer.

1. Download `nodefmt-0.7.0.zip` from the [releases](https://github.com/carjimcor/blender-nodefmt/releases),
   or build it with `tools/build.sh`.
2. In Blender: Edit > Preferences > Get Extensions > the arrow menu > Install from Disk, and pick
   `nodefmt-0.7.0.zip`. It is enabled on install.

## Use

In a Geometry Nodes, Shader or Compositor editor, open the sidebar (N) and the nodefmt tab:

- **Sort Current Tree**: the tree shown in the editor.
- **Sort All Trees**: every node tree in the file.
- **Check Current Tree**: reports which rules the tree breaks, with their codes, without
  changing it. Use it on a tree you edited by hand; the result appears in the panel.
- **Rules**: one checkbox per style rule, "Thorough search" (several seeds, slower) and "Use
  nodefmt.toml". The same options are in Preferences > Add-ons > nodefmt.

Each sort is one undo step: Ctrl+Z puts the tree back.

## Rules

Every behaviour is a rule with a code. Guarantees always hold; style rules can be switched off.

| Code | Name | Kind | What it does |
|---|---|---|---|
| NF001 | no-curved-links | guarantee | A link that is not straight turns on reroutes. |
| NF002 | no-links-behind-nodes | guarantee | No wire passes behind a node. |
| NF003 | orthogonal-segments | guarantee | Every segment is horizontal or vertical (within half a unit) at the UI scale used. |
| NF004 | no-overlapping-reroutes | guarantee | No two reroutes of different wires closer than 10 units. |
| NF005 | logic-unchanged | guarantee | A sort that would change the logic is undone. |
| NF010 | duplicate-input-nodes | style | Input-like nodes get a copy next to each distant group of consumers. |
| NF011 | commutative-swaps | style | The two inputs of a commutative node may be swapped to remove a crossing. |
| NF020 | free-zone-outputs | style | A zone's output may sit where its inputs are instead of level with the zone input. |
| NF021 | blocks-next-to-consumer | style | A frame or zone with nothing linked into it sits right before the node it feeds. |
| NF022 | converging-shape | style | A tree that converges on one output may take a ">" shape. |
| NF030 | staircase-bundles | style | Wires leaving or entering one node are nested like stairs and do not cross. |
| NF031 | no-u-jogs | style | No U-jogs, landings or tiny steps that a free height would remove. |
| NF032 | wire-clearance | style | Wires keep clear of node edges, frame borders and zone outlines. |
| NF033 | avoid-crossings | style | A crossing that can be avoided is avoided. |
| NF034 | no-junction-look | style | Wires never share a point or run on one line. |
| NF040 | label-first-reroute | style | A reroute label goes on the first reroute of its wire. |

## Configuration

A `nodefmt.toml` next to the .blend file or in a folder above it (for example the repository
root) sets the rules; `[tool.nodefmt]` in a `pyproject.toml` works too.

```toml
select = ["ALL"]        # codes, prefixes ("NF03") or names
ignore = ["NF011"]      # rules switched off
thorough = false        # true: search with several seeds (slower)
ui-scale = 1.4          # the Resolution Scale to sort for (default: Blender's)
```

In the add-on the file wins over the checkboxes while "Use nodefmt.toml" is on.

## Command line and pre-commit hook

Blender must run with its window (not `-b`): node sizes and socket positions only exist once
Blender draws a tree. The window opens for a few seconds.

```
blender file.blend --python nodefmt_cli.py -- --check [--select CODES] [--ignore CODES] [--strict]
blender file.blend --python nodefmt_cli.py -- --fix   [--tree NAME] [--ui-scale 1.4] [--thorough]
blender file.blend --python nodefmt_cli.py -- --list-rules
```

`--check` prints one line per violation with its code and exits 1 if a tree is not sorted or
breaks a guarantee (with `--strict`, on any violation). `--fix` sorts and saves the file, and
exits 2 if a tree could not be sorted without changing its logic (that tree is left as it was).

For a git pre-commit hook, copy `hooks/pre-commit` to `.git/hooks/pre-commit` and set `BLENDER`
(the Blender executable) and `NODEFMT` (the path of `nodefmt_cli.py`). It checks every staged
`.blend` file and stops the commit if one is not sorted.

## Supported editors

- Geometry Nodes: every node group.
- Shader: materials, worlds, lights and shader node groups.
- Compositor: the scene's compositor and compositor groups.

Zones (Repeat, Simulation, For Each Element, Closure) and frames work in every editor.

## Limitations

- **UI scale.** Wires are exact at one UI scale, the one the tree was sorted at. Blender does not
  scale socket offsets evenly, so at another scale links are off by a few units and `--check`
  reports the tree. Sort at the scale you work at.
- **Blender version.** Socket positions are read from Blender's internal data with ctypes
  (`sockets.py`), which matches Blender 5.2 and must be checked for each new version.
- **Speed.** Large trees take 1 to 20 seconds each; "Thorough search" about twice as long.
- Some crossings are unavoidable (for example inside a bundle of wires that swap places); the
  layout puts them where they are clean.
- Inserting a node usually adds a column, so a small edit can reorder what is before it.
- "Keep layout" mode is experimental.
- Line style and texture node trees are not supported.

## Roadmap

- A progress bar while sorting, with the steps done and the steps left.
- Sort only the selection: the contents of a selected frame, or the selected nodes and
  reroutes, keeping the selection.

## How it works

The pipeline (ranking, crossing reduction, placement, orthogonal routing, search) and its
references are described in [docs/ALGORITHM.md](docs/ALGORITHM.md). The demo animation is built
by `tools/make_demo.sh` (`scramble.py`, `dump_tree.py`, `animate.py`); `animate.py` runs nodefmt
offline with its snapshot hook and draws each phase.

## Contributing

Contributions are welcome. The project is maintained in spare time, so reviews may take a while.
Every pull request that changes a layout must show it: before and after screenshots of the
affected trees, and the `.blend` file or steps to reproduce. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## AI use

This add-on is vibe coded: all of its code, documentation, tools and the demo animation were
written by AI ([Claude Code](https://claude.com/claude-code)). My part was the idea, the style
rules, reviewing the results in Blender and deciding what to change.

## Credits and license

`nodefmt/sockets.py` is adapted from [Node Arrange](https://extensions.blender.org/add-ons/node-arrange/)
1.12.1, licensed GPL-2.0-or-later; its notice is kept in the file.

nodefmt is licensed under the GNU General Public License v3.0 or later ([LICENSE](LICENSE)).
