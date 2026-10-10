# Limitations

- **UI scale.** Wires are exact at one UI scale, the one the tree was sorted at. Blender does not
  scale socket offsets evenly, so at another scale links are off by a few units and `--check`
  reports the tree. Sort at the scale you work at.
- **Blender version.** Socket positions are read from Blender's internal data with ctypes
  (`sockets.py`), which matches Blender 5.2 and must be checked for each new version.
- **Speed.** Large trees take 1 to 20 seconds each; "Thorough search" about twice as long.
- Some crossings are unavoidable (for example inside a bundle of wires that swap places); the
  layout puts them where they are clean.
- Inserting a node usually adds a column, so a small edit can reorder what is before it.
- "Keep layout" mode is experimental.
- Line style and texture node trees are not supported.
