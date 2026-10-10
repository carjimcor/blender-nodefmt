# Changelog

## Unreleased

- Shorter README; the details moved to `docs/` (usage, rules, configuration, command line,
  limitations, roadmap).
- One example per rule in `examples/NF0xx.blend`, built by `tools/make_examples.py`, with before
  and after screenshots in `docs/RULES.md` (`tools/capture_examples.py`, `tools/finish_images.py`).
- Tests from the examples: `tests/run_tests.py`.
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
