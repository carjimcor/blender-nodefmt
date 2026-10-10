# Changelog

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
