# Usage

For installing, see the [README](../README.md#install).

## Supported editors

- Geometry Nodes: every node group.
- Shader: materials, worlds, lights and shader node groups.
- Compositor: the scene's compositor and compositor groups.

Zones (Repeat, Simulation, For Each Element, Closure) and frames work in every editor.

## The panel

In a node editor, open the sidebar (N) and the nodefmt tab.

- **Sort Current Tree**: sorts the tree shown in the editor.
- **Sort Selection**: sorts only the selected nodes and reroutes, or what is inside a selected
  frame (see [Sort Selection](#sort-selection)).
- **Sort All Trees**: sorts every node tree in the file. A tree that cannot be sorted without
  changing its logic is left as it was and reported.
- **Check Current Tree**: lists the rules the tree breaks, without changing it (see
  [Check](#check)).
- **Mode**: *Relayout* (default) builds a new layout: columns, order and wires. *Keep layout
  (experimental)* keeps your columns and order and only straightens wires and fixes reroutes.
- **Wires exact at UI scale**: the Resolution Scale the wires are made exact for (see
  [Limitations](LIMITATIONS.md)).
- **Check** and **Capture** sections: the last check result, and [Capture Tree](#capture).
- **Rules** (closed at first): one checkbox per style rule (see [Rules](RULES.md)), also in
  Preferences > Add-ons > nodefmt. While "Use nodefmt.toml" is on and a `nodefmt.toml` is found,
  the file wins over the checkboxes and the panel shows its name (see
  [Configuration](CONFIGURATION.md)).

## Sorting

A sort lays the tree out left to right in columns, orders each column to remove crossings, lines
links up so that most are straight, and routes the rest as orthogonal wires on reroutes. With the
default rules it also:

- copies input-like nodes (Group Input, Named Attribute, ...) next to distant consumers (NF010);
- swaps the inputs of commutative nodes (Add, Multiply, AND, ...) to remove a crossing (NF011);
- keeps frames and zones together, puts a self-contained frame right before the node it feeds,
  and a frame linked to nothing compactly under the tree (NF021);
- keeps labelled reroutes on their wires, one label at the start of each wire, clear of other
  labels, nodes and wires (NF040, NF041).

NF022 converging-shape, NF023 stacked-fields and NF035 fanned-multi-inputs are off by default; see
[Rules](RULES.md) for what they do.

- **Undo**: each sort is one undo step; Ctrl+Z puts the tree back.
- **Logic check**: every sort compares a logic fingerprint of the tree before and after (nodes,
  values, links, the order of multi-input links). If anything differs, the tree is restored and
  the sort reports an error.
- **Fractional UI scale** (1.25, 1.4, ...): the first sort may move a tree down so that it lies
  wholly below y = 0, where the node sizes nodefmt measures hold (see
  [How it works](ALGORITHM.md#orthogonal-wires)). After that it stays put.

### Progress

While a sort runs, the status bar and the top of the panel show the tree, the pass and the step,
for example "Tree 3/14 Wire: pass 1 (of at most 6), layout 4/9 (step 6/14)", with a progress bar
and the time since the sort started. "layout 4/9" counts the containers: the tree itself, each
zone and each frame.

The tree is laid out again as long as a pass still moves something (copying input nodes or
swapping inputs changes the graph), up to six passes. Most trees take two: the second finds
nothing to move. The bar assumes two passes, so on a tree that needs more it stays near 99% while
the later passes run.

Esc cancels the sort and puts every tree back as it was (no undo step is added). The editor takes
no other input while a sort runs.

## Sort Selection

Select some nodes and reroutes, or a frame (everything inside it is sorted), and press Sort
Selection. The rest of the tree does not move.

- The part is laid out like a whole tree, as one block. Links from the rest enter it on its left
  edge, links to the rest leave it on its right edge.
- The block keeps the top-left corner of the part. If it grew and would overlap a node of the
  rest, it moves down or right (whichever is less) until it is clear.
- Links between the part and the rest are drawn orthogonally on new reroutes, around what is in
  the way when a clear route exists.
- Reroutes of the part are rebuilt; selected reroutes on wires that do not touch the part are left
  alone. A frame whose nodes are all in the part moves with them.
- The selection is kept (the same nodes plus the new reroutes), the logic check holds, and the
  sort is one undo step.
- Input-like nodes are not copied (NF010): a copy would add nodes outside the selection.

| Before: the frame "Sort me" is selected | After Sort Selection |
|---|---|
| ![A tree with a messy frame selected](images/selection-before.png) | ![The frame sorted, the rest in place](images/selection-after.png) |

The tree is `examples/selection.blend`. The sorted frame is wider than before, so it moved down
to clear Mesh to Points; its links to the rest go around the nodes in the way.

## Check

Check runs every enabled rule on the tree as Blender draws it, and tries a sort on a copy of the
layout (undone at once): if the sort would move anything, the tree is reported as not formatted
(NF900). It changes nothing. Right after a sort whose last pass moved nothing, Check skips that
trial sort as long as nothing changed since (layout, node sizes, labels, rules, UI scale), so it
is much faster.

![The Check section of the panel and the marks in the editor](images/check-panel.png)

The Check section shows the result:

- **No problems: the tree is sorted** when nothing is broken.
- Otherwise a line says whether the tree is sorted ("Sorted; these style rules could not be met")
  or not ("Not sorted: Sort Current Tree fixes it"), then one row per broken rule: an icon (a
  warning for the guarantees and NF900, an info sign for style rules), the code, the name and how
  many places break it.
- **Click a rule** to select the nodes and reroutes of its next place and frame them in the
  editor; click again for the next place. The place shown is described under its row.
- **Marks in the editor**: a ring with the rule code at each place (red for the guarantees and
  NF900, orange for style rules). The overlay toggle in the header of the Check section turns them
  on and off.
- Once the tree changes, or the editor shows another tree, the panel asks you to check again and
  the marks are hidden.

A tree sorted with the same rules and UI scale reports nothing, or only style violations the
formatter could not avoid (for example a crossing inside a bundle of wires that swap places).
NF900 and NF010 have no single place: they mark the nodes a sort would move or copy. The image
shows `examples/NF032.blend` after Check, with NF032 clicked.

The same check runs from the [command line](CLI.md) with `--check`. Each violation is also
printed to the system console.

## Capture

Capture Tree saves an image of the whole tree shown in the editor (inside a group, that group) at
a zoom you choose, even when the tree is much larger than the screen. It never changes the tree
and adds no undo step.

![A tree saved with Capture Tree](images/capture.png)

The image above was made with Capture Tree at zoom 1, from `examples/selection.blend` after Sort
Current Tree.

Options, in the Capture section of the panel:

- **Zoom**: screen pixels per node unit. At 1, node text is as large as Blender draws it at UI
  scale 1. Blender's largest zoom is about 2.3 times the UI scale; above that the largest is used.
- **Whole Tree** or **Selection**: the selected nodes only, or a selected frame with its content.
- **Margin**: empty pixels around the tree.
- **Hide Overlays** (on by default): hides the context path, gizmos and the marks of Check. Wire
  colours, timings and node previews stay.
- **File**: the PNG file, or a folder for `<tree name>.png`. Empty: a `captures` folder next to
  the .blend file, or the temporary folder if the file is not saved. An existing file is
  replaced.
- **Copy to Clipboard**: also copies the image, to paste it into another program.
- **Open in Image Editor**: shows the image in an Image Editor of the window, or in a new window.

The editor is maximised, its header, toolbar and sidebar hidden, and the view is moved across the
tree with one screenshot per step. The screenshots overlap, are checked against each other and
are joined inside Blender (no extra Python packages). Blender dims a wire whose ends are both far
outside the view, except the wires of selected nodes, so while it captures every node is
selected and the theme's selection colours are set to the normal ones: nodes look unselected and
long wires keep their colour. Afterwards the selection, the theme and the editor are put back as
they were.

While it runs, the status bar shows the step ("tile 3/12") and Esc cancels; nothing is saved. The
panel then reports the file, its size, the number of screenshots and the time. As a guide, a tree
of 100 nodes takes about a second at zoom 1 and four seconds at zoom 2 on a 1920 x 1080 screen.
The image is at most 200 megapixels; a larger capture is refused before it starts.

The clipboard uses Blender's own image copy. It was tested on Windows only; Blender also supports
it on macOS and Linux, depending on the version and display system. If Blender cannot copy, the
capture says so and the file is saved all the same.

The same capture runs from the [command line](CLI.md) with `--capture`.
