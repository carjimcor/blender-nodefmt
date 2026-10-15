# nodefmt

A formatter for Blender node trees, in the spirit of code formatters such as
[ruff](https://github.com/astral-sh/ruff) or [black](https://github.com/psf/black). It sorts a
tree into columns, orders the nodes to remove crossings, lines links up and routes the rest as
orthogonal wires on reroutes. It never changes what the tree computes, and sorting a sorted tree
changes nothing. It can also save any node tree, sorted or not, as one image of the whole tree
(see [Capture whole trees](#capture-whole-trees)).

<p align="center"><img src="media/nodefmt-demo.webp" alt="A messy node tree being sorted step by step: links become direct lines, nodes slide into columns, columns are reordered, heights settle and orthogonal wires are drawn" width="960"></p>

The animation shows the steps on a messy tree ([MP4](media/nodefmt-demo.mp4),
[GIF](media/nodefmt-demo.gif)). The same tree in Blender, before and after:
[media/before-after.png](media/before-after.png).

## Why another layout tool

Blender already has tools that tidy node trees:
[Node Arrange](https://extensions.blender.org/add-ons/node-arrange/) lays out a whole tree quickly,
Node Wrangler aligns selected nodes, and relax brushes move nodes by hand. None of them gave the
result I wanted: straight wires that only turn at right angles, nothing behind nodes, and a style
that can be tuned rule by rule. nodefmt is slower, but more configurable, and in my opinion its
result is more satisfying.

## What it guarantees

- **Logic never changes**: a sort that would change what the tree computes is undone.
- **No curved wires and nothing behind nodes**: a link that is not straight turns at right
  angles on reroutes, and no wire passes behind a node.
- **Orthogonal at your UI scale**: every drawn segment is exactly horizontal or vertical.
- **Idempotent and deterministic**: the same tree always gives the same layout.

## Install

Blender 5.2 or newer. Download the `nodefmt-<version>.zip` of the latest
[release](https://github.com/carjimcor/blender-nodefmt/releases) (or build it with
`tools/build.sh`), then in Blender: Edit > Preferences > Get Extensions > the arrow menu > Install
from Disk.

## Quick use

In a Geometry Nodes, Shader or Compositor editor, open the sidebar (N) and the nodefmt tab:

- **Sort Current Tree**: the tree shown in the editor.
- **Sort Selection**: only the selected nodes, or what is inside a selected frame.
- **Sort All Trees**: every node tree in the file.
- **Check Current Tree**: the rules the tree breaks, without changing it; click a rule to see
  where.
- **Capture Tree**: saves a PNG of the whole tree at a chosen zoom, larger than the screen if
  needed.

Esc cancels a sort, and each sort is one undo step.

## Capture whole trees

Capture Tree saves the whole tree as one PNG at the zoom you choose, however large the tree:
the editor is moved across it and the screenshots are joined into one image. It works on any
tree, sorted or not, never changes it and adds no undo step. Long wires keep their colour (in an
ordinary screenshot Blender dims a wire whose ends are both off screen). The image can also be
copied to the clipboard, for an issue, a forum post or documentation.

![A tree saved with Capture Tree](docs/images/capture.png)

In the panel: the Capture section, then Capture Tree (zoom, margin, whole tree or selection,
file). From the command line (Blender opens its window for a moment and closes itself):

```
blender file.blend --python nodefmt_cli.py -- --capture "Tree name" --out tree.png --zoom 1.0
```

Details in [Usage](docs/USAGE.md#capture) and [Command line](docs/CLI.md).

## Documentation

- [Usage](docs/USAGE.md): the panel, Sort Selection, Check and Capture.
- [Rules](docs/RULES.md): every rule with its code, an example and what switching it off does.
- [Configuration](docs/CONFIGURATION.md): `nodefmt.toml`.
- [Command line](docs/CLI.md): `--check`, `--fix`, `--capture` and the git pre-commit hook.
- [Limitations](docs/LIMITATIONS.md) and [Roadmap](docs/ROADMAP.md).
- [A large real tree](docs/EXAMPLE.md): a 115-node tree from Blender Stack Exchange, before and
  after.
- [How it works](docs/ALGORITHM.md): the layout pipeline and its references.

## Contributing

Contributions are welcome; reviews may take a while. A pull request that changes a layout must
show it with before and after screenshots. See [CONTRIBUTING.md](CONTRIBUTING.md), which also
explains how to run the tests.

## AI use

This add-on is vibe coded: all of its code, documentation, tools and the demo animation were
written by AI ([Claude Code](https://claude.com/claude-code)). My part was the idea, the style
rules, reviewing the results in Blender and deciding what to change.

## Credits and license

`nodefmt/sockets.py` is adapted from [Node Arrange](https://extensions.blender.org/add-ons/node-arrange/)
1.12.1 by Leonardo Pike-Excell, licensed GPL-2.0-or-later; its notice is kept in the file and the
extension's manifest credits it. Node Arrange worked out how to read socket positions from
Blender's runtime data, which nodefmt depends on: thank you.

nodefmt is licensed under the GNU General Public License v3.0 or later ([LICENSE](LICENSE)).
