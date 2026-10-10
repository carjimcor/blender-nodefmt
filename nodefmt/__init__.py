# SPDX-License-Identifier: GPL-3.0-or-later
"""nodefmt: a formatter for Blender node trees ("ruff for nodes"): Geometry Nodes, shader
(materials, worlds, lights, shader groups) and compositor trees.

Lays a tree out left to right with straight main links and orthogonal routing (every drawn wire
segment is exactly horizontal or vertical at the UI scale of the session; a link that is not
straight turns on reroutes; none passes behind a node), aligned with the nodes it connects
rather than with the grid, frames and zones kept together. Input-like nodes (Group Input, Named
Attribute, Position, ...) get copies next to distant consumers, the inputs of commutative nodes
(Add, Multiply, AND, Equal, ...) may be swapped to remove crossings, and labelled reroutes stay
on their wires (one label at the start of each wire). Never changes logic: every format is
checked against a logic fingerprint and undone if anything differs.

Every behaviour is a rule with a code (rules.py, as in ruff): guarantees NF001-NF005 always hold,
style rules can be switched off in nodefmt.toml, on the command line or in the add-on.

Two ways to use it:
- Add-on (extension): Node Editor > Sidebar > nodefmt: "Sort Current Tree", "Sort All Trees",
  "Check", "Capture Tree" (an image of the whole tree, capture.py) and the rule toggles.
- Command line (git pre-commit hook): blender file.blend --python nodefmt_cli.py -- --check | --fix
"""


def register():
    """Register the add-on (its operators and panel)."""
    from . import ui
    ui.register()


def unregister():
    """Unregister the add-on."""
    from . import ui
    ui.unregister()
