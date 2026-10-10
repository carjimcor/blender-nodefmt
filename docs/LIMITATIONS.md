# Limitations

- **UI scale.** Wires are exact at one UI scale, the one the tree was sorted at. Blender does not
  scale socket offsets evenly, so at another scale links are off by a few units and `--check`
  reports the tree. Sort at the scale you work at.
- **Blender version.** Socket positions are read from Blender's internal data with ctypes
  (`sockets.py`), which matches Blender 5.2 and must be checked for each new version.
- **Speed.** Large trees take 1 to 20 seconds each; "Thorough search" about twice as long.
- Some crossings are unavoidable (for example inside a bundle of wires that swap places); the
  layout puts them where they are clean.
- Blender shows a wire's label, greyed, on every reroute after the labelled one. Where the wire
  turns upwards it runs through that copy, and labels on the turns into a multi-input socket
  (a slot apart) cannot all be clear of each other.
- A commutative swap that a frame or zone cannot leave to the level around it (one input from
  inside the block, or a port that feeds other nodes too) is decided inside the block, which
  does not see where the outside wire comes from.
- Inserting a node usually adds a column, so a small edit can reorder what is before it.
- "Keep layout" mode is experimental.
- Sort Selection lays the part out on its own: its links to the rest are routed afterwards and
  may cross other wires or take long detours, and a part that grows may have to move down or
  right to clear the nodes around it. Sort the whole tree for the best result.
- Line style and texture node trees are not supported.
- Capture Tree: Blender dims a wire whose two ends are both far outside the view, so in a
  capture larger than the screen a long wire can look fainter in the middle than at its ends.
  In a tree with zones the margin is a little wider, to leave room for the zone outlines. The
  zoom is at most about 2.3 times the UI scale, and the image at most 200 megapixels.
  Something the mouse hovers over when the capture starts may be drawn highlighted.
