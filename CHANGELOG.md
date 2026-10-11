# Changelog

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
