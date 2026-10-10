# Roadmap

Planned work, in order of priority. Nothing here is promised; ideas may change once they are
tried.

## 1. Labels for long wires

A wire that runs far from its source is hard to follow: at its destination you cannot see where
it comes from. nodefmt already keeps the labels you put on reroutes (NF040, NF041). This extends
them:

- A wire counts as long when it crosses more than a set number of columns, configurable in
  `nodefmt.toml` and in the add-on.
- Only wires that leave a frame or a custom node group get a label, since their output stands for
  a step that has a name. The label is the group output's socket name, or the frame's label. A
  wire from a plain node such as Map Range gets none: its socket name says nothing about what the
  value means.
- A label you put on a reroute always wins: nodefmt carries it along the wire as it does now.
- The label goes on the first reroute of the wire; Blender repeats it, greyed, on the others.

It will be a style rule that can be switched off, working together with NF040 and NF041.

## 2. Frames inside a frame

A frame that only groups other frames, with nothing linked between them, is laid out as a stack
today, and its children can change order. The children should keep the order you gave them and
line up on a common axis, side by side or centred on one vertical line, instead of being
reshuffled. To be explored.

## 3. Curved mode (experimental)

An alternative to the orthogonal style for people who prefer Blender's curved links. Wires would
use few reroutes and rely on Blender's own curves; wires that go to the same place or to nearby
places would run parallel, like pipes, both on straight runs and through their curves. A curve is
never built from many reroutes.

The curvature of links is a theme setting (Preferences > Themes > Node Editor > Noodle Curving),
so the result depends on each user's theme; this mode would be tuned for the default curvature.
