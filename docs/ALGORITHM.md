# How nodefmt works

This page describes the layout pipeline, the guarantees behind it and the algorithms it builds
on. For using the add-on, see [Usage](USAGE.md).

The core is pure Python: only reading a tree and writing the result need Blender (`model`,
`layout`, the engine modules, `routes` and `measure` run without it), so the layout can be tested
on trees saved as plain data. In the add-on, a sort runs one step at a time
(`api.format_steps`, `Formatter.run_steps`) so the panel can show progress between steps.

## The layout in short

- **Columns.** Data flows left to right in columns. The main input of a node (its geometry input,
  else its first linked input) is reached by a straight horizontal link wherever possible. A link
  that is not straight turns twice at right angles on reroutes, on a vertical track in the gap
  between two columns (NF001-NF003).
- **Multi-input sockets.** Each link into a Join Geometry or Join Strings arrives on its own,
  level with its slot (a quarter widget unit apart), never through a fork. With NF035 they arrive
  a widget unit apart, each at a fan point left of the socket, and converge from there.
- **Crossings** cost more than a bend (NF033). A lane (a wire that passes columns) may run above
  or below the nodes of its columns, whichever crosses less; a wire from outside a zone may enter
  above the zone input; crossings inside a bundle are avoided by nesting tracks like stairs
  (NF030).
- **Blocks.** Frames and zones stay together. A big block with nothing linked into it sits right
  before its consumer and reaches left over the earlier columns (NF021). A zone's content hangs
  below the zone input's top line.
- **Wire paths.** No U-jog or landing that a free height could remove (NF031), no wire along a
  node edge, frame border or zone outline (NF032), no shared points, wires on one line or reroutes
  in the middle of a straight run (NF034). A final pass over the whole drawing (`wires.tidy`)
  fixes what the layout of a single container cannot see.
- **Alignment** with connected nodes comes first; the 20-unit grid does not matter.
- **Zone outputs** (with the nodes chained right before them) sit where their inputs are, or level
  with the zone input, whichever costs less (NF020). This holds for every paired zone (Repeat,
  Simulation, For Each Geometry Element, Closure, ...).
- Mix Shader is not commutative (its factor picks a side).

## Pipeline

1. **Draw** (`draw.py`). Blender computes node sizes and socket positions only while drawing a
   node editor, so `Editor.show(tree)` shows the tree and forces one redraw. Socket positions are
   read from Blender's runtime data with `ctypes` (`sockets.py`), after checking that the data
   layout matches. Shader and compositor trees are pinned in their editor; a Geometry Nodes group
   used by a modifier is shown through its object (see [Orthogonal wires](#orthogonal-wires)).
2. **Model** (`model.py`). `read(tree)` turns the drawn tree into plain data: nodes (box, socket
   offsets, type), links resolved through reroutes, and labelled reroutes as label records. Every
   reroute is removed (only dangling ones stay), so the layout starts from direct links and
   reroutes are only made after placement. `Model` derives main inputs, multi-input slots,
   commutative pairs and frame paddings.
3. **Duplicates** (`dup.py`). Input-like nodes that compute the same thing form a class. The
   class is merged into one node, the merged tree is laid out, the consumers are grouped by
   container, column and distance, and each group far from the others gets its own copy. The plan
   does not depend on the copies that exist now, so a second sort changes nothing.
4. **Containers** (`layout.py`). Zones and frames are laid out inside out: a child becomes one box
   (a compound item) of its parent, with ports where links cross its border. A zone comes with two
   layouts, its output level with the zone input or free (step 8), and the parent keeps the one
   that makes the two cheapest together. A commutative pair whose swap only exchanges two ports of
   a block is left to the parent, which sees where both wires come from and tries the pair both
   ways (NF011).
5. **Ranking** (`ranking.py`). Longest-path layering: every node gets a column after all its
   sources, as far right as its consumers allow. The Group Output and a zone's output take the
   last column, a zone's input the first. A big block (three or more columns) gets columns of its
   own, except a satellite (NF021): a big block with nothing linked into it takes the column right
   before its first consumer and reaches left over the earlier columns (`columns.py`). A container
   with satellites is laid out with and without them, and the cheaper is kept.
6. **Lanes** (`ranking.py`). A link that spans several columns gets one dummy per column it
   crosses, shared by every link from the same output socket (a bus with taps).
7. **Ordering** (`ordering.py`, `force.py`). Crossing reduction: an initial order from the last
   column back, barycenter sweeps down and up (weighted towards main inputs), transposition of
   neighbours and swaps of commutative inputs, counting crossings between socket heights. A second
   order comes from a force-directed relaxation: links are springs, items in a column repel each
   other, and each column is sorted by the heights they settle at.
8. **Placement** (`placement.py`, `relax.py`). Three ways to find heights for a given order:
   - `blocks`: links are made straight in order of priority (geometry flow, main inputs, bundles,
     lanes) by merging the items they join into blocks, as long as no column overlaps and the
     layout does not grow too tall; then the blocks are compacted (separation constraints from
     the column order, each block pulled to the weighted median of what its links want), with a
     weak pull towards a common top line;
   - `balanced` (NF022): the same without the pull to the top line;
   - `relax`: spring relaxation (each item moves to the weighted mean of what its links want, each
     column restacked by isotonic regression), then nearly straight links are straightened.

   In a zone, each placement runs with each zone output mode (`ZONE_OUT`): `level` keeps the zone
   output on the zone input's line; `median` and `mean` free it, with a soft pull to that line
   (`ZONE_LEVEL`) plus the pull of its links. A free zone output drags the nodes aligned with it.
   Blender draws the zone frame around its nodes by itself.
9. **Columns and tracks** (`columns.py`). Column x positions come from the widest node, with one
   vertical routing track per source socket in each gap. Tracks are ordered to avoid crossings:
   exactly (dynamic programming over subsets) for up to 8 tracks, else by moves of single tracks.
   Crossings inside a bundle and wires that run into another wire's corner cost more. Tracks one
   above the other (10 units apart or more, as two reroutes must be) then share one x (NF036).
   Gaps widen where a labelled wire turns next to a node (NF041). Items with no link at all go
   under the layout where it grows least (NF021).
10. **Cost and search** (`cost.py`, `search.py`, `engine.py`). Every candidate is laid out in full
    and priced by the [layout cost](#layout-cost). The cheapest is improved by a local search
    whose moves change one choice: a zone port above or below the zone input, a satellite to
    either end of its column, a lane or the wires of one node to the top or bottom, a commutative
    swap, the placement method, a node to the top or bottom, two neighbours swapped. A final slide
    pass moves a group of nodes held by straight links up or down when that makes one more link
    straight. Then the current layout is tried as well ([stability](#determinism-and-stability)).
    Budgets count layouts, not seconds, so the result is deterministic. In a zone, the level and
    the free output modes are searched apart and both go to the parent (step 4).
11. **Routing** (`routes.py`, `wires.py`). The route segments of all containers become one reroute
    tree per source socket: shared points become taps, points where a route goes straight on are
    dropped. With NF035, `Model._fan` gives each multi-input slot a fan point: the layout routes
    the link to it, the node reaches out on its left by the fan's depth so the tracks stay clear,
    and `Formatter.place` adds the last stretch to the slot. Then the whole drawing is tidied
    (`wires.tidy`): almost level runs are made level (NF034), and single horizontal runs move to
    another free height when that removes a crossing, a U-jog, a landing or a run along an edge
    (NF031-NF034). Labels go back on the first reroute of their wire (NF040), where their text and
    its greyed copies are clear (NF041, `labels.py`).
12. **Write back** (`blend.py`). Node locations (on the pixel grid), new reroutes and links are
    written to Blender. New links are made before old reroutes are removed, so no input is left
    unlinked on the way, and links into a multi-input socket are made again in their original
    order. Then `ortho.straighten` makes every drawn segment orthogonal, reroutes left in the
    middle of a straight run are removed, and if straighten nudged the Group Output the whole tree
    moves back by as much.
13. **Logic check and revert** (`check.py`, `api.py`). A logic fingerprint is taken before and
    after (see [NF005](RULES.md#nf005-logic-unchanged)); on any difference or error the tree is
    restored from a snapshot and the sort reports a failure. Only the node tree is compared and
    changed: settings of a material, world or scene outside it are never touched. The tree is
    laid out again until a pass moves nothing (normally two passes, at most six).
14. **Checks** (`lint.py`, `metrics.drawing`, `api.check_tree`). The tree as Blender draws it
    becomes the same drawing the tidy pass works on, and each rule has a test on it. NF010
    compares the copy plan, NF011 looks for crossing wires into a commutative pair, and NF900 (not
    formatted) tries a sort on a snapshot. Right after a sort whose last pass moved nothing, NF900
    is known to hold as long as the tree's state (layout, node sizes, labels, rules, UI scale) is
    unchanged, so the trial sort is skipped.

### Snapshots

`Formatter(model, record=True)` keeps plain-data snapshots of the phases in
`formatter.snapshots`: the tree with direct links ('direct'), the orders, seeds, search and slide
of each container, and the final drawing ('final'). `tools/animate.py` uses them for the demo
animation.

## Orthogonal wires

A segment counts as orthogonal when its ends differ by at most 0.5 node units in x or in y. The
formatter guarantees this for every drawn segment, at the UI scale it ran at.

**Why the UI scale matters.** Blender draws a node at its location rounded to whole pixels
(location times the UI scale) and its sockets whole pixels below that; a reroute's dot sits
exactly at its location. At UI scale 1 a pixel is a node unit and everything lines up. At another
scale (Resolution Scale 1.25, 1.5, ..., or a display set to 150%):

- socket offsets in node units are not the scale-1 ones divided evenly, so a layout made at scale
  1 is a few units off at 1.5;
- at fractional scales Blender rounds the height of each row of a node towards zero, row after
  row from its top, so the rows of a node above y = 0 are a pixel taller than below it, and a tall
  node is several units taller above 0.

No layout is exact at two scales at once, so:

1. The layout is made at the UI scale of the session. The command line uses the preferences
   Blender starts with: run it without `--factory-startup`, or give `--ui-scale`.
2. Node locations go on that scale's pixel grid (`ortho.to_px`). Every node is measured drawn
   below y = 0 (`api.read_tree`), and the sort puts the whole tree below 0, moving it down the
   first time if it reached above (`Formatter.place`). So the measures hold wherever the layout
   puts a node, and a sort settles in two passes as at scale 1. Sort Selection cannot move the
   tree: it measures the nodes of the part both ways and `model.at` gives each the offsets of
   where it is.
3. After writing, `ortho.straighten` reads back what Blender drew and removes what rounding left,
   until nothing is off: reroutes take the exact height of the socket their wire runs to, and
   reroutes joined by a wire share one height or x; a straight link a little off moves its
   destination node (else its source) onto the line, at most 4 units and 3 times per node; what
   is still off gets an extra bend. The diagonal stretch of an NF035 fan is left as it is
   (`ortho.fanned`).
4. Check and `--check` test every drawn segment, so a file sorted at another scale is reported.

A Geometry Nodes group that a modifier uses, directly or nested, is drawn through that object, as
the user sees it: some nodes (Bake) draw more rows there than in a pinned editor.

## Determinism and stability

- **One deterministic pass.** The search runs one seed, so the same input always gives the same
  layout. More seeds (`params.SEEDS`, for experiments) lower the layout cost by about 3% on the
  test trees, a difference hard to see, for about 3 times the time.
- **Idempotent.** Sorting a sorted tree changes nothing (`--check` passes right after `--fix`):
  tested on 106 trees at UI scale 1 and 1.4.
- **The current layout is the tie-breaker.** Besides the fresh layout (which depends on the graph
  only), each container is also laid out in the order its nodes and wires have now, without
  search. That one is kept when it costs no more than the fresh one (`params.STABLE`, 0 by
  default; None turns it off). On a sorted tree the fresh layout is the current one. The copy plan
  of input nodes and the choice of satellite blocks (NF021) depend on the graph only.
- **Stability after a small edit.** Inserting a node usually adds a column, which shifts what is
  before it; the tie-breaker keeps more of the order. Over 16 small edits of the test trees, 729
  of 5172 pairs of nodes changed their relative order with it and 835 without. Two starting
  layouts of one graph can therefore sort differently when both results cost the same.

## Layout cost

The cost of a container's layout is a weighted sum (`params.py`, section "layout cost"):

| weight | value | applies to |
|---|---|---|
| `W_CROSS` | 4 | each clean crossing: a horizontal and a vertical wire, away from bends (`NEAR_RR` 10) and sockets (`NEAR_SOCK` 20) |
| `W_CROSS_BAD` | 12 | each crossing near a bend, a reroute or a socket |
| `W_CROSS_BUNDLE` | 15 | extra for each crossing of two wires that leave the same node or enter the same node |
| `W_OVERLAP` | 40 | each pair of wires of different sources on one line, or closer than `COLLINEAR` (6) |
| `W_CLASH` | 40 | each reroute closer than `RR_CLEAR` (10) to another, or closer than `ON_WIRE` (6) to another wire |
| `W_BEND` | 3 | each link that is not straight (it needs two reroutes) |
| `W_JOG` | 8 | extra for a bend smaller than `JOG` (30): a small step looks like a mistake |
| `W_VLEN` | 0.004 | each unit of vertical wire |
| `W_SRC` | 0.01 | each unit a link from a source node drops or rises |
| `W_GRID` | 0 | each node off the 20-unit grid (off: the grid does not matter) |
| `W_H` | 0.01 | each unit of height |
| `W_W` | 0.005 | each unit of width |
| `W_HLEN` | 0.002 | each unit of horizontal wire (NF021: wires across the whole tree cost) |
| `W_BORDER` | 2 | each horizontal run on the top or bottom line of a zone's outline (NF032) |
| `W_LABEL` | 6 | each label (or greyed copy) over another label, a node or a wire (NF041) |
| `W_LABEL_BEND` | 1 | extra for each labelled link that is not straight: its turns show the label twice more (NF041) |

The other constants in `params.py` set spacing, search budgets, placement methods and zone output
modes.

## Algorithms and references

- Layered drawing (ranking, ordering, coordinate assignment): K. Sugiyama, S. Tagawa, M. Toda,
  "Methods for visual understanding of hierarchical system structures", IEEE Transactions on
  Systems, Man, and Cybernetics 11(2), 1981.
- Barycenter and median crossing reduction: Sugiyama et al. 1981; P. Eades, N. Wormald, "Edge
  crossings in drawings of bipartite graphs", Algorithmica 11, 1994.
- Transposition of neighbours and long edges as chains of dummies: E. R. Gansner, E. Koutsofios,
  S. C. North, K.-P. Vo, "A technique for drawing directed graphs", IEEE Transactions on Software
  Engineering 19(3), 1993.
- Blocks of aligned links and their compaction, and the balanced variant: U. Brandes, B. Köpf,
  "Fast and simple horizontal coordinate assignment", Graph Drawing 2001. nodefmt aligns by link
  priority instead of medians and compacts with its own constraint solver.
- Compaction with separation constraints (merging colliding blocks): T. Dwyer, K. Marriott,
  P. J. Stuckey, "Fast node overlap removal", Graph Drawing 2005 (VPSC).
- Ports and orthogonal routing between layers: C. D. Schulze, M. Spönemann, R. von Hanxleden,
  "Drawing layered graphs with port constraints", Journal of Visual Languages and Computing 25(2),
  2014 (Eclipse Layout Kernel, ELK Layered).
- Force-directed placement: T. M. J. Fruchterman, E. M. Reingold, "Graph drawing by
  force-directed placement", Software: Practice and Experience 21(11), 1991.
- Restacking a column with the least weighted displacement: pool adjacent violators for isotonic
  regression, M. Ayer et al., Annals of Mathematical Statistics 26(4), 1955.
- Track order: an instance of linear ordering, solved by dynamic programming over subsets
  (Held-Karp style) for small gaps and by local search otherwise.
- Search: local search over the discrete choices of the layout.

## Files

```
nodefmt/  (the extension)
  __init__.py   add-on entry (register)
  blender_manifest.toml  extension manifest
  ui.py         sidebar panel, buttons, progress, Check results and marks, rule toggles
  capture.py    Capture Tree: tiled screenshots of a tree joined into one PNG
  rules.py      rule codes and names, nodefmt.toml, --select/--ignore, parameters per rule
  lint.py       checks: the rules a drawn tree breaks, with codes
  wires.py      the drawn wires of a whole tree: faults, tidy pass, zone outlines
  api.py        sort a tree with logic check and revert; checks; the trees of a file
  draw.py       make Blender draw a tree (node sizes, socket positions)
  sockets.py    socket positions from Blender's runtime data (ctypes; from Node Arrange)
  ortho.py      UI scale, pixel grid, multi-input slots; read back and straighten drawn wires
  model.py      read a tree as plain data; the Model the layout works on
  dup.py        copies of input-like nodes: plan (pure) and realize (Blender)
  part.py       Sort Selection: a part of the tree with pins for its links
  layout.py     containers, nesting, absolute positions, routes, labels, geometry()
  engine.py     layout of one container: the driver (seeds, search, slide)
  graph.py      items, edges, candidates and shared helpers of the engine
  params.py     tunable constants and cost weights
  ranking.py    columns and lanes
  ordering.py   crossing reduction
  force.py      force-directed ordering
  placement.py  block placement and compaction ('blocks', 'balanced')
  relax.py      spring relaxation and straightening ('relax')
  columns.py    column and track positions, track order
  cost.py       routes and layout cost
  search.py     local search and slide pass
  routes.py     reroute trees and label placement
  labels.py     reroute labels as Blender draws them: text width, greyed copies, overlaps
  blend.py      write a layout to Blender
  check.py      logic fingerprint, snapshot and restore
  measure.py    layout metrics of plain geometry (tests)
  metrics.py    layout metrics of a drawn tree in Blender (tests), and its wires.Drawing
nodefmt_cli.py  command line (check, fix, capture)
hooks/pre-commit  git hook that checks staged .blend files
tools/
  build.sh      build and validate the extension zip (dist/)
  scramble.py   a messy, reproducible copy of a tree (demo start)
  dump_tree.py  a tree as JSON: nodefmt's model data and Blender's theme colours
  animate.py    the demo animation, rendered offline from the snapshots
  make_demo.sh  scramble, dump and animate in one go
  bench.py      time the offline layout on a folder of dumped trees, with an output fingerprint
  make_examples.py     the rule examples (examples/NF0xx.blend, NF0xx-<what>.blend)
  capture_examples.py  screenshots of the examples before and after a sort
  finish_images.py     crop and compress them into docs/rules/
examples/       one small tree per rule that breaks it
tests/
  run_tests.py  tests from the examples (check, sort, logic, idempotency, rule off)
  test_operators.py  the add-on operators: progress, Esc, undo, Sort Selection, Check, Capture
docs/           usage, rules, configuration, command line, limitations, this page
```
