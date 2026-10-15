# Configuration

A `nodefmt.toml` next to the .blend file or in a folder above it (for example the repository
root) sets the rules; the first one found wins. `[tool.nodefmt]` in a `pyproject.toml` works
too.

```toml
select = ["ALL"]        # codes, prefixes ("NF03") or names
ignore = ["NF011"]      # rules switched off
ui-scale = 1.4          # the Resolution Scale to sort for (default: Blender's)
```

- `select`: the style rules to apply and check: `"ALL"`, codes (`"NF031"`), prefixes (`"NF03"`
  selects NF030-NF039) or names (`"no-u-jogs"`). Default: all but NF022 converging-shape,
  NF023 stacked-fields and NF035 fanned-multi-inputs, which are off unless selected (by code,
  prefix, name or `"ALL"`).
- `ignore`: rules to switch off, in the same forms. Guarantees (NF001-NF005) cannot be switched
  off.
- `ui-scale`: the Resolution Scale the wires are made exact for. By default, the scale Blender
  runs at.

A rule that is off is neither applied when sorting nor reported by a check.

In the add-on the file wins over the checkboxes while "Use nodefmt.toml" is on. On the command
line, `--select` replaces the file's `select` and `--ignore` adds to its `ignore` (see
[CLI](CLI.md)).
