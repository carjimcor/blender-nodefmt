# SPDX-License-Identifier: GPL-3.0-or-later
"""nodefmt: a formatter for Blender node trees ("ruff for nodes"): Geometry Nodes, shader
(materials, worlds, lights, shader groups) and compositor trees.

Lays a tree out left to right with straight main links and orthogonal wires (every drawn segment
horizontal or vertical at the session's UI scale, bends on reroutes, none behind a node), frames
and zones kept together. Input-like nodes (Group Input, Named Attribute, ...) may get copies next
to distant consumers, and the inputs of commutative nodes (Add, Multiply, ...) may be swapped to
remove crossings. Logic never changes: every format is checked against a logic fingerprint and
undone if anything differs.

Every behaviour is a rule with a code (rules.py, as in ruff): guarantees NF001-NF005 always hold,
style rules can be switched off in nodefmt.toml, on the command line or in the add-on.

Two ways to use it:
- Add-on: Node Editor > Sidebar > nodefmt: sort the current tree, the selection or all trees,
  check a tree, capture an image of it (capture.py), and the rule toggles.
- Command line (git pre-commit hook): blender file.blend --python nodefmt_cli.py -- --check | --fix
"""


def register():
    """Register the add-on (its operators and panels)."""
    from . import ui
    ui.register()


def unregister():
    """Unregister the add-on."""
    from . import ui
    ui.unregister()
