# Command line and pre-commit hook

Blender must run with its window (not `-b`): node sizes and socket positions only exist once
Blender draws a tree. The window opens for a few seconds.

```
blender file.blend --python nodefmt_cli.py -- --check [--select CODES] [--ignore CODES] [--strict]
blender file.blend --python nodefmt_cli.py -- --fix   [--tree NAME] [--ui-scale 1.4] [--thorough]
blender file.blend --python nodefmt_cli.py -- --list-rules
blender file.blend --python nodefmt_cli.py -- --capture TREE [--out FILE.png] [--zoom 1.0]
```

| Option | What it does |
|---|---|
| `--check` | Reports violations, changes nothing. |
| `--fix` | Sorts and saves the file, then reports what is left. |
| `--list-rules` | Prints the rules and exits. |
| `--capture TREE` | Saves an image of tree `TREE` (names as for `--tree`) and exits; changes nothing. |
| `--out PATH` | `--capture`: the PNG file, or a folder (default: a `captures` folder next to the .blend file). |
| `--zoom Z` | `--capture`: screen pixels per node unit (default 1.0). |
| `--margin PX` | `--capture`: empty pixels around the tree (default 40). |
| `--select CODES` | Rules to apply and check: comma-separated codes, prefixes or names (default ALL). |
| `--ignore CODES` | Rules to switch off (added to the config file's `ignore`). |
| `--thorough` | Search with several seeds (slower; the default is one deterministic pass). |
| `--config PATH` | A `nodefmt.toml` to use (default: the first one found from the .blend's folder up). |
| `--ui-scale S` | The Resolution Scale to sort for (default: Blender's, or the config's). |
| `--tree NAME` | Only this tree (repeatable): a group name, or `"Material: <name>"`, `"World: <name>"`, `"Light: <name>"`. |
| `--no-format-check` | `--check`: report rule violations only, without trying a sort (NF900). |
| `--statistics` | Print the number of violations per rule. |
| `--strict` | `--check`: fail on any violation. |

`--check` prints one line per violation with its code, as ruff does, and exits 1 if a tree is
not sorted (NF900) or breaks a guarantee (NF001-NF005); with `--strict`, on any violation. A
style rule that a sorted tree still breaks (the formatter could not do better, for example a
crossing inside a bundle) is reported but fails the check only with `--strict`.

Each tree gets a progress line, `[3/14] sorting Wire` (or `checking`); on a terminal `--fix`
also shows the steps of the sort on one line that is overwritten as it goes on.

`--fix` sorts and saves the file, and exits 2 if a tree could not be sorted without changing
its logic (that tree is left as it was).

Wires are exactly orthogonal at the UI scale the tree is sorted at. Run without
`--factory-startup` so Blender uses your preferences (your Resolution Scale), or give the scale
with `--ui-scale` or `ui-scale` in `nodefmt.toml` (set for that run only; preferences are never
saved).

`--capture` works as Capture Tree in the add-on (see [Usage](USAGE.md#capture)) and exits 3 if
the tree is not found or the image would be too large. A Geometry Nodes tree is shown through
the object that uses it, so it looks as in the editor; `--ui-scale` sets the scale it is drawn
at. The file is never saved.

## Pre-commit hook

Copy `hooks/pre-commit` to `.git/hooks/pre-commit` and set `BLENDER` (the Blender executable)
and `NODEFMT` (the path of `nodefmt_cli.py`). It checks every staged `.blend` file and stops the
commit if one is not sorted. `NODEFMT_UI_SCALE` sets the scale and `NODEFMT_ARGS` adds options
(for example `--strict`). Fix a file with:

```
blender file.blend --python nodefmt_cli.py -- --fix
```
