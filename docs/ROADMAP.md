# Roadmap

Planned work, in order of priority. Nothing here is promised; ideas may change once they are
tried.

## 1. Labels for long wires

At the end of a long wire you cannot see where it comes from. nodefmt already keeps the labels
you put on reroutes (NF040, NF041); this would add labels of its own:

- A wire counts as long when it crosses more than a set number of columns, configurable in
  `nodefmt.toml` and in the add-on.
- Only wires that leave a frame or a custom node group get a label: the frame's label, or the
  group output's socket name. A wire from a plain node such as Map Range gets none, since its
  socket name says nothing about what the value means.
- A label you put on a reroute always wins.
- The label goes on the first reroute of the wire; Blender repeats it, greyed, on the others.

It will be a style rule that can be switched off, working together with NF040 and NF041.

## 2. Frames inside a frame

A frame that only groups other frames, with nothing linked between them, is laid out as a stack
today, and its children can change order. They should keep the order you gave them and line up
on a common axis instead. To be explored.

## 3. Lint rules for Check

Linters for programming languages also report code that works but is hard to read or maintain.
Check could do the same for node trees, with a second family of rules that are only reported,
never fixed by a sort. Each would have a code, could be switched off like the style rules, and
have its limits set in `nodefmt.toml` or in the add-on. They would use their own range of codes
(for example NL001...), so `select` and `ignore` can take them as a group.

First candidates:

- **tree-too-complex**: more than a set number of nodes (for example 150, reroutes and frames
  not counted): "Tree is too complex (212 nodes, limit 150); consider moving parts into node
  groups."
- **unused-nodes**: nodes whose result reaches no output of the tree.
- **unused-group-sockets**: group inputs that nothing reads, or outputs that nothing feeds.
- **muted-nodes**: muted nodes or links left in the tree.
- **unlabelled-frames**: frames without a label.
- **repeated-subtree**: the same group of nodes, with the same links and settings, appears more
  than once; a candidate for a node group.

## 4. Sorting a part of a tree

Sort Selection lays the selected nodes out on their own and then routes their links to the rest,
which can cross other wires or take long detours. It should place the part with the rest in
view, or be replaced by something narrower that works reliably. One candidate: **sort a
branch**, the nodes that feed the selected node (its upstream), laid out in front of it while
the rest stays where it is, as some other node editors do.

## 5. Command line without a window

The command line needs Blender's window, because socket positions only exist once a node editor
has been drawn, so it cannot run with `blender -b`, for example in CI. To be explored: drawing
off screen, or computing socket positions from Blender's node layout rules without drawing.

## 6. Very large trees

Blender's own "Curve to Tube" node group (392 nodes, 31 frames) sorts correctly but not well: it
takes about 18 minutes, and its frames end up almost all in one row, so the tree becomes a long
strip with wires across most of it, wider and harder to read than its hand-made layout. To work
on: packing frames into rows and columns instead of a single row, and the speed of the layout
search on trees of this size.
