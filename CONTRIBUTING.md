# Contributing

Thanks for helping. nodefmt is maintained in spare time: issues and pull requests are welcome and
will be reviewed, but replies may take a while.

## Reporting a layout problem

Open an issue with:

- a screenshot of the tree before sorting and after sorting, with the problem marked;
- the `.blend` file, or a small one that shows the problem;
- your Blender version and Resolution Scale (Preferences > Interface).

## Pull requests

- Keep each pull request to one change.
- Show the effect: before and after screenshots of every tree whose layout changes, at the same
  zoom, and the `.blend` file or steps to reproduce. A change without them will not be reviewed.
- Run the tests (below) and `--check` on the trees you tested, and say which rules (NF codes)
  the change affects.
- The logic check must still pass: sorting must never change what a tree computes.
- Code, comments and documentation are in English. New functions get a docstring.
- New behaviour that changes the style gets a rule code, so it can be switched off, and an
  example in `examples/` if it can be shown.

## Run the tests

```
blender --factory-startup --python tests/run_tests.py
blender --factory-startup --python tests/run_tests.py -- --only NF031 --verbose
```

Blender opens its window for a few seconds (node sizes only exist once a tree is drawn) and
closes itself. `--factory-startup` gives a fixed UI scale of 1.0. For every example in
`examples/` the tests check that:

- the check reports the example's rule on the original tree (NF020 has no geometric check:
  there, that the tree is not formatted);
- after a sort with the default rules it no longer does, the logic fingerprint is unchanged, no
  reroute is left leading nowhere, and a second sort changes nothing;
- for a style rule, a sort with the rule switched off does not show its behaviour, where that is
  observable in the example.

The run prints a table with one row per example and exits with 1 if any test fails.

The add-on operators (progress, Esc, undo) have their own tests, which press Esc through
Blender's event simulation:

```
blender --factory-startup --enable-event-simulate --python tests/test_operators.py
```

## Tools

- `tools/build.sh`: build and validate the extension zip in `dist/`.
- `tools/make_examples.py`: rebuild `examples/NF0xx.blend` (run with Blender's window:
  `blender --factory-startup --python tools/make_examples.py`).
- `tools/capture_examples.py` and `tools/finish_images.py`: the before and after images of
  [docs/RULES.md](docs/RULES.md), at UI scale 1.0 (the second needs Pillow):

  ```
  blender --factory-startup --python tools/capture_examples.py -- <tmp_dir>
  python tools/finish_images.py <tmp_dir>
  ```

- `tools/make_demo.sh`: the demo animation in `media/` (`scramble.py` makes a messy copy of a
  tree, `dump_tree.py` reads it as JSON, `animate.py` runs nodefmt offline with its snapshot
  hook and draws each phase).
