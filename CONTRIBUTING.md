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
  zoom. A change without them will not be reviewed.
- Run `--check` on the trees you tested and say which rules (NF codes) the change affects.
- The logic check must still pass: sorting must never change what a tree computes.
- Code, comments and documentation are in English. New functions get a docstring.
- New behaviour that changes the style gets a rule code, so it can be switched off.
