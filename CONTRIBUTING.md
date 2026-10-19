# Contributing

Thanks for helping. nodefmt is maintained in spare time: issues and pull requests are welcome and
will be reviewed, but replies may take a while.

## Reporting a layout problem

Open an issue with:

- a screenshot of the tree before and after sorting, with the problem marked;
- the `.blend` file, or a small one that shows the problem;
- your Blender version and Resolution Scale (Preferences > Interface).

## Pull requests

- Keep each pull request to one change.
- Show the effect: before and after screenshots of every tree whose layout changes, at the same
  zoom, and the `.blend` file or steps to reproduce. A change without them will not be reviewed.
- Run the tests (below) and `--check` on the trees you tested, and say which rules (NF codes) the
  change affects.
- Format and lint with ruff 0.17.1 (configured in `ruff.toml`): `ruff format .` and `ruff check .`.
  Every pycodestyle rule is on, with no exceptions; CI fails on any error or unformatted file.
  The easiest way is pre-commit, which runs ruff and the layout check on each commit:
  `pip install pre-commit`, then `pre-commit install`.
- The logic check must still pass: sorting must never change what a tree computes.
- Code, comments and documentation are in English. New functions get a docstring.
- New behaviour that changes the style gets a rule code, so it can be switched off, and an
  example in `examples/` if it can be shown.

## Continuous integration

Every push to `main` and every pull request runs two checks on GitHub Actions
(`.github/workflows/ci.yml`), without Blender:

- **ruff**: `ruff check .` and `ruff format --check .`.
- **layouts unchanged**: the layout core is pure Python, so it sorts every example, dumped as
  JSON in `tests/layout/trees/`, and compares each result with `tests/layout/baseline.json`. A
  change that alters a layout by accident fails here.

A change that alters layouts on purpose updates the baseline in the same pull request, and shows
the before and after of those examples:

```
python tools/bench.py tests/layout/trees --runs 1 --save tests/layout/baseline.json
```

After changing the examples (`tools/make_examples.py`) or what nodefmt reads from a tree, dump
them again first: `blender --factory-startup --python tools/dump_examples.py`.

The Blender tests below need Blender's window, so they run on your machine, not in CI: say in the
pull request that they pass.

## Run the tests

```
blender --factory-startup --python tests/run_tests.py
blender --factory-startup --python tests/run_tests.py -- --only NF031 --verbose
```

Blender opens its window for a few seconds (node sizes only exist once a tree is drawn) and
closes itself. `--factory-startup` gives a fixed UI scale of 1.0; NF034 is tested at 1.25 and
NF003-rows at 1.4, the scales their examples are made for.

Each example in `examples/` (a second example of a rule is `NF0xx-<what>.blend`) is tested for:

- **check**: the check reports the example's rule on the tree as saved. Rules with no geometric
  check (NF005, NF020, NF022, NF023, NF036) must be reported as not formatted (NF900) instead.
- **only**: a sort with only that rule (for a guarantee: no style rule) removes the violation,
  keeps the logic and leaves no reroute leading nowhere. For NF020, NF022, NF023 and NF036 the
  layout must show the rule's effect.
- **off**: for a style rule, a sort with every style rule off keeps the violation (or does not
  show the effect), so the difference between the two is the rule's own.
- **sort, fixed, logic, again**: after a sort with the default rules (plus the example's rule if
  it is off by default) the rule is no longer reported, the logic fingerprint is unchanged, no
  reroute leads nowhere, and a second sort changes nothing.
- **extra**: tests of single examples, such as NF003-rows: no wire is left with a step too small
  to see (two reroutes closer than 10 units); NF022: the output is between its inputs after both
  sorts, also the one with the default rules.

`examples/selection.blend` tests Sort Selection three ways (the frame, two nodes, two nodes with a
third between them): the rest does not move, the part keeps its corner or moves just enough,
nothing overlaps, its wires are orthogonal and behind no node, the logic and the selection are
kept, and a second sort changes nothing.

The run prints a table with one row per example and exits with 1 if any test fails.

The add-on operators (progress, Esc, undo, Sort Selection, Check, Capture Tree) have their own
tests, which press Esc through Blender's event simulation. Capture Tree is tested at UI scales
1.0 and 1.4.

```
blender --factory-startup --enable-event-simulate --python tests/test_operators.py
```

## Tools

- `tools/build.sh`: build and validate the extension zip in `dist/`.
- `tools/dump_examples.py`: dump the examples as JSON for the CI layout check (see above).
- `tools/make_examples.py`: rebuild the examples in `examples/`
  (`blender --factory-startup --python tools/make_examples.py`).
- `tools/capture_examples.py` and `tools/finish_images.py`: the before and after images of
  [docs/RULES.md](docs/RULES.md), at UI scale 1.0 (the second needs Pillow):

  ```
  blender --factory-startup --python tools/capture_examples.py -- <tmp_dir>
  python tools/finish_images.py <tmp_dir>
  ```

- `tools/make_demo.sh`: the demo animation in `media/`. `scramble.py` makes a messy copy of a
  tree, `dump_tree.py` saves it as JSON, `animate.py` runs nodefmt offline and draws each phase.
- `tools/bench.py`: times the offline layout on a folder of trees saved with `dump_tree.py`, with
  a fingerprint of the output. Before a change that should only make the code faster, save a
  baseline, then check that every fingerprint is the same (any Python 3, Blender's bundled one
  too):

  ```
  python tools/bench.py <trees_dir> --save base.json
  python tools/bench.py <trees_dir> --compare base.json
  python tools/bench.py <trees_dir> --only <name> --profile
  ```
