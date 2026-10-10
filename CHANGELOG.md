# Changelog

## Unreleased

- Shorter README; the details moved to `docs/` (usage, rules, configuration, command line,
  limitations).
- One example per rule in `examples/NF0xx.blend`, built by `tools/make_examples.py`, with before
  and after screenshots in `docs/RULES.md` (`tools/capture_examples.py`, `tools/finish_images.py`).
  A style rule is shown sorted with every style rule off and with only that rule, so the two
  images differ only by what the rule does; NF005 shows the same logic fingerprint in both.
- Tests from the examples: `tests/run_tests.py`. Each rule on its own removes its example's
  violation, and every style rule off keeps it.
- Fix: with NF034 the only wire rule on (NF031-NF033 off), the pass that tidies the drawn wires
  did not run, so wires on one line or reroutes on another wire were left as they were.
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
- Fix: when input-like nodes were copied, or a Group Input showed sockets it did not use (NF010),
  a wire that reached its destination through reroutes was relinked directly and its reroutes,
  a labelled one included, were left leading nowhere.

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
