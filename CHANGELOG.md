# Changelog

## 0.13.0

With the default rules, node positions are the same as in 0.12.0: some wires lose a tiny step
and some reroutes change frame. NF022 (off by default) now changes layouts when it is on.

- New setting `straight-tolerance` (screen pixels, default 2): a wire that close to the
  horizontal or vertical is left as it is instead of getting a bend of two reroutes, and a
  reroute left in the middle of such a run is removed (NF034). Rounding to whole pixels leaves
  some sockets a pixel or two apart, and the tiny step looked worse than the wire a pixel off.
  It is in `nodefmt.toml`, the `--straight-tolerance` option and the add-on preferences; 0 gives
  every step its bend, as before. The NF003 check uses the same tolerance.
- New reroutes belong to the frame they lie in: a reroute that nodefmt places inside a frame
  becomes a child of the innermost frame that holds it, so it moves with the frame, and one
  outside every frame has no parent. Only the frame's inner area counts, not its padding, so a
  reroute never makes Blender grow the frame. A tree sorted with an earlier version is reported
  as not formatted (NF900) until it is sorted again.
- NF022 converging-shape now gives the ">" shape it describes. It used to try one more
  placement, without the pull to the top line, and keep it when it cost less; with the default
  rules on (NF010, NF030 or NF033 is enough) that placement gave the same layout as the others,
  so the rule did nothing. Now each branch stays by its own inputs, and the node the output
  depends on moves halfway between the branches that meet there, with the nodes after it, as far
  as the columns allow. A geometry flow stays straight, and links that all enter one multi-input
  socket are left alone. Layouts with NF022 off, the default, are unchanged.
- Fix: Capture Tree could leave the node editor's selection colours changed for good. It sets
  three theme colours while it runs, and the theme is part of the preferences: if Blender saved
  them during a capture (auto-save on quit), the changed colours stayed. The capture now turns
  the auto-save of preferences off while it runs, and afterwards puts it back and leaves the
  preferences marked as unchanged if they were.

## 0.12.0

No change in how trees are laid out: the layouts are the same as in 0.11.1.

- Esc works during a sort of any size. The copy plan and the layout run in a worker thread, so
  Blender stays responsive however long a step takes, and Esc puts the tree back and stops the
  thread. Node locations are written in one call instead of one update per node, and new reroutes
  and links are made in short slices (Blender's "Curve to Tube", 617 nodes: the window froze for
  up to 78 s at a time; now never more than 0.7 s, and Esc cancels in about 3 s).
- A tree linked from a library (such as an Essentials asset added as a link) is no longer sorted:
  the file keeps only the link, so the sort would be lost on reload. Sort Current Tree and Sort
  Selection are unavailable there, with the reason in their tooltip, and the panel says to make
  the tree local first.
- Fix: on macOS, Capture Tree saved tiles of an earlier frame (from a script, the whole screen
  repeated), because a screenshot there reads the frame shown before the last one. The window is
  now drawn twice before each tile on macOS; Windows and Linux are unchanged.

## 0.11.1

No change in how trees are sorted or checked: the layouts are the same as in 0.11.0.

- New tagline in Blender's extension list: "A rule-based formatter for Blender node trees".
- The code base passes a strict ruff configuration (every pycodestyle rule) and is formatted
  with ruff format; CI on GitHub Actions checks it and that the example layouts are unchanged.

## 0.11.0

- New rule NF035 fanned-multi-inputs, off by default: the links into a multi-input socket (Join
  Geometry, Join Strings, ...) arrive a widget unit apart and converge in a short fan right
  before the socket, clear of the wires into the node's other inputs, instead of running a
  quarter widget unit apart (examples `NF035` and `NF035-strings`).
- New rule NF036 shared-tracks: vertical runs one above the other in a gap (10 units apart or
  more) share one x instead of a staircase of tracks, which also makes gaps narrower (example `NF036`).
- Capture Tree: long wires keep their colour. Blender dims a wire whose ends are both far outside
  the view, except the wires of selected nodes, so the capture selects every node and sets the
  theme's selection colours to the normal ones while it runs, then puts both back.
- Large trees sort about twice as fast again, with identical layouts: the block placement updates
  the layout's height incrementally after each tentative merge instead of recomputing it, and the
  label check (NF041) only tests the wires near each label (Blender's "Curve to Tube", 392 nodes:
  one layout pass from 577 s to 251 s).
- Fix: in a gap widened for a reroute label (NF041), the last tracks could fall on the next
  column, right on a node's input socket; the wire then ran through the socket and the sort
  failed its logic check and was undone (seen on Blender's own "Curve to Tube", 392 nodes). The
  gap now holds every track.
- Socket positions are checked before they are used: on a Blender version whose internal socket
  data has another layout, a sort or a check stops with a clear message instead of placing nodes
  from wrong data.
- Fix: at a fractional UI scale, Check (or the next sort) moved a reroute a pixel onto the pixel
  grid, away from the height straighten had given it, and reported a segment 0.7 units off
  (NF003). Reroutes are no longer snapped to the grid: their dot sits exactly at their location.
- NF022 converging-shape is off by default: on the test trees the ">" shape left more crossings
  (317 against 299 without it). Select it to keep it.
- Check right after a sort is much faster (a 115-node tree at UI scale 1.4: 33 s to 7 s): when
  the sort ended because a pass moved nothing, the check knows the tree is formatted as long as
  nothing changed since (layout, node sizes, labels, rules, UI scale), instead of sorting it
  again on a copy.
- At a fractional UI scale (1.25, 1.4, ...) a sort puts the whole tree below y = 0, moving it
  down the first time if it reached above. Blender draws the rows of a node a pixel taller above
  0 than below, so measures changed with where the layout put each node and a sort could take
  up to six passes; now every node is measured once, below 0, and a sort settles in two passes
  (a 115-node tree at UI scale 1.4: 130 s to 28 s).
- Faster sorting, with exactly the same layouts: about 3x on a 115-node Geometry Nodes tree
  (a sort in Blender from 96 s to 32 s), and up to 48x on trees with a gap crossed by many
  wires (the order of the wires in a gap is now found without summing every pair again). The
  local search reuses the cost of layouts it has tried before, the block placement keeps its
  blocks and their constraints up to date instead of rebuilding them for every merge, the
  wire checks of the tidy pass look only at wires nearby, and the copy plan of input nodes no
  longer routes the wires it does not use.
- Removed the "Thorough search" option (`thorough` in nodefmt.toml, `--thorough`): it took about
  three times as long for layouts hard to tell apart. The copy plan of input nodes runs one seed.
- `tools/bench.py`: time the offline layout on a folder of dumped trees and compare the output
  with a saved baseline.

## 0.10.0

- New rule NF023 stacked-fields, off by default: a short chain of field nodes (up to three, such
  as Index -> Compare) that feeds one input of a node and nothing else is stacked above or below
  that node, in its column, with its wires round the side (example `NF023`).
- Fix: a chain of nodes fed only by input nodes (Index -> Compare) and used only inside a zone
  is laid out inside the zone, next to where it is used, instead of before the zone with wires
  across all of it.
- Fix: a zone nested in another zone (a Repeat inside a Closure) that holds an input node used
  only there (Index, Position) failed to sort ("'NoneType' object has no attribute 'parent'").

## 0.9.0

- Capture Tree: saves a PNG of the whole tree shown in the editor (or of the selection) at a
  chosen zoom, larger than the screen if needed. The editor is maximised and moved across the
  tree, one screenshot per step; the screenshots are checked against each other and joined
  inside Blender with numpy, then the editor is put back as it was. Options: zoom, margin, hide
  overlays, file, copy to the clipboard, open in an Image Editor. Progress in the status bar,
  Esc cancels, no undo step, the tree never changes. Command line: `--capture TREE --out FILE`.
- The progress shows the time since the sort started and the pass limit ("pass 2 (of at most
  6)"), and the docs explain why a large tree can stay near 99% while later passes run.
- docs/EXAMPLE.md: a large real tree from Blender Stack Exchange, before and after.

## 0.8.1

- Fix: at a fractional UI scale, a wire into a low socket of a tall node (or out of one) could
  end in a step too small to see, two reroutes on one spot that look like a slanted stub.
  Blender rounds each row of a node towards zero, so a node above y = 0 is taller than below it;
  every node is now measured both ways and laid out with the offsets of where it is drawn
  (NF003; example `NF003-rows`). Measured sizes no longer carry float noise that could move a
  column by a grid step from one pass to the next.
- Fix: the two inputs of a commutative node in a frame or zone were not swapped when both wires
  came from outside the block, since the block is laid out before what is around it. Such a swap
  is now made by the level around the block, which sees where the wires come from (NF011;
  examples `NF011-frame`, `NF011-zone`).
- New rule NF041 label-clearance: a reroute label, and the greyed copies Blender shows on the
  later reroutes of its wire, overlap no other label, node or wire. Gaps widen where a labelled
  wire turns next to a node, and a label goes on the first reroute where its text is clear (or
  a new one before it). Check measures label text as Blender draws it.
- NF021: a frame or zone with nothing linked at all sits under the tree where it makes the tree
  grow least, beside the blocks above it instead of under all of them; Check reports one that
  could sit higher (example `NF021-alone`).
- A second example of a rule is `examples/NF0xx-<what>.blend`, tested and shown like the others.

## 0.8.0

- Sort Selection: sorts only the selected nodes and reroutes, or what is inside a selected
  frame, and leaves the rest of the tree where it is. The part keeps its top-left corner (or
  moves down or right to clear the nodes around it), its links to the rest are routed
  orthogonally around what is in the way, and the selection is kept.
- Check is visual: the panel lists the rules broken, with an icon, the code, the name and the
  number of places; clicking a rule selects and frames its next place. Marks in the editor show
  each place with its rule code (a toggle in the Check header), and "No problems: the tree is
  sorted" when there is nothing. A result that no longer matches the tree is not shown. The
  rule toggles moved to a Rules section, closed at first. Command line output is unchanged.
- Sorting shows its progress in the status bar and the panel ("Tree 3/14 Wire: pass 1, layout
  4/9 (step 6/14)"), and Esc cancels it and puts the trees back. Still one undo step. The command
  line prints a progress line per tree. Operator tests: `tests/test_operators.py`.
- Shorter README; the details moved to `docs/` (usage, rules, configuration, command line,
  limitations).
- One example per rule in `examples/NF0xx.blend`, built by `tools/make_examples.py`, with before
  and after screenshots in `docs/RULES.md` (`tools/capture_examples.py`, `tools/finish_images.py`).
  A style rule is shown sorted with every style rule off and with only that rule, so the two
  images differ only by what the rule does; NF005 shows the same logic fingerprint in both.
- Tests from the examples: `tests/run_tests.py`. Each rule on its own removes its example's
  violation, and every style rule off keeps it.
- Fix: when input-like nodes were copied, or a Group Input showed sockets it did not use (NF010),
  a wire that reached its destination through reroutes was relinked directly and its reroutes,
  a labelled one included, were left leading nowhere.
- Fix: with NF034 the only wire rule on (NF031-NF033 off), the pass that tidies the drawn wires
  did not run, so wires on one line or reroutes on another wire were left as they were.

## 0.7.0

First public version.

- Sidebar buttons "Sort Current Tree", "Sort All Trees" and "Check Current Tree"; each sort is
  one undo step.
- Every behaviour is a rule with a code: guarantees NF001-NF005 always hold, style rules
  NF010-NF040 can be switched off in the add-on, in `nodefmt.toml` (or `[tool.nodefmt]` in
  `pyproject.toml`) or on the command line (`--select`, `--ignore`).
- `--check` lists violations with their codes, as ruff does; `--fix` sorts and saves.
- One deterministic pass by default; "Thorough search" runs several seeds.
- The current layout breaks ties, so a sorted tree stays as it is.
- Blocks with nothing linked in (NF021) sit right before the node they feed.
- Crossings cost more than bends: lanes may run above or below the nodes and wires may enter a
  zone above its input.
- A final pass over the whole drawing keeps wires off node edges and zone outlines and removes
  U-jogs.
- Geometry Nodes, Shader and Compositor trees.
- Packaged as a Blender extension (`blender_manifest.toml`).
