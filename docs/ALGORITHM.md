# How nodefmt works

This page describes the layout pipeline, the guarantees behind it and the algorithms it builds
on. For installing and using the add-on, see [Usage](USAGE.md). The core is pure Python:
only reading a tree and writing the result need Blender (`model`, `layout`, the engine modules,
`routes` and `measure` run without it), so the layout can be tested on trees saved as plain
data.

In the add-on, "Sort Current Tree" and "Sort All Trees" run the format described here, one step
at a time (`api.format_steps`, `Formatter.run_steps`), so the panel can show progress between
steps.

## The layout in short

- Data flows left to right in columns. The main input of a node (its geometry input, else its
  first linked input) is reached by a straight horizontal link wherever possible. A link that is
  not straight turns twice at right angles on reroutes, on a vertical track in the gap between
  two columns (NF001-NF003), into multi-input sockets too: each link into a Join Geometry or Join
  Strings arrives on its own, level with its slot (a quarter widget unit apart), never through a
  fork. With NF035 (off by default) these links arrive a widget unit apart, each at its fan point
  left of the socket, and converge from there in a short diagonal fan.
- Crossings: a crossing costs more than a bend (NF033). A lane (a wire that passes columns) may
  run above or below the nodes of its columns, whichever crosses less; a wire from outside a
  zone may enter above the zone input instead of crossing the wires that leave the zone input
  downwards; crossings inside a bundle are avoided by nesting the tracks like stairs (NF030).
- Blocks: frames and zones stay together. A big block with nothing linked into it (a frame that
  starts from its own Group Input) is placed right before its consumer and reaches to the left
  over the earlier columns, above or below them (NF021). A zone's content hangs below the zone
  input's top line; only the wires that enter above the zone input run above it.
- Wire paths: no U-jog and no landing that a free height could remove (NF031), no wire along a
  node's edge, a frame's border or a zone's outline (NF032), no shared points, no wires on one
  line, no reroute in the middle of a straight run (NF034). A pass over the whole drawing
  (`wires.tidy`) moves single runs to better heights across container borders, where the layout
  of one container cannot see.
- Alignment with the connected nodes comes first; the 20-unit grid does not matter.
- A zone's output (with the nodes chained right before it, such as a Join Geometry) sits where its
  inputs are, or level with the zone input, whichever costs less (NF020); zones are found by
  `paired_output`, so this holds for every paired zone (Repeat, Simulation, For Each Geometry
  Element, Closure, ...).
- Mix Shader is not commutative (its factor picks a side).

## Pipeline

1. **Draw** (`draw.py`). Blender computes node sizes and socket positions only while drawing a
   node editor. `Editor.show(tree)` shows the tree in a node editor and forces one redraw.
   Socket positions are read from Blender's runtime data with `ctypes` (`sockets.py`). Shader
   and compositor trees are pinned in a Shader or Compositor editor; a Geometry Nodes group used
   by a modifier is shown through its object (see "Orthogonal wires").
2. **Model** (`model.py`). `read(tree)` turns the drawn tree into plain data: nodes (box, socket
   offsets, type), links resolved through reroutes, and labelled reroutes as label records.
   Every reroute is removed from the model, labelled ones included (only dangling reroutes stay
   as nodes), so the layout starts from nodes linked directly; reroutes are only made after
   placement. `Model` derives main inputs, multi-input slots, commutative pairs and frame
   paddings.
3. **Duplicates** (`dup.py`). Input-like nodes that compute the same thing form a class. The
   class is merged into one node, the merged tree is laid out, the consumers are grouped by
   container, column and distance, and each group far from the others gets its own copy
   (existing copies are reused; Blender's own duplicate makes new ones). The plan does not depend
   on the copies that exist now, so a second format changes nothing.
4. **Containers** (`layout.py`). Zones (an input, its output and everything between) and frames
   are laid out inside out: a child container becomes one box (a compound item) of its parent,
   with ports where links cross its border. A zone comes with two layouts, its output level
   with the zone input or free (step 8); the parent is laid out with each and keeps the one that
   makes the two cheapest together, so a lowered zone output is kept only when what follows the
   zone fits it. A commutative pair inside a block whose swap only exchanges two of its ports
   (the node is in the block's first column, or each input comes straight from a port that
   feeds nothing else) is left to the parent, which sees where the two wires come from: the
   compound gets the pair of ports, and the parent is laid out with the pair as the block left
   it and with it free, keeping the cheaper (NF011). Nested blocks pass such a pair on up.
5. **Ranking** (`ranking.py`). Longest-path layering: every node gets a column after all its
   sources, as far right as its consumers allow; the Group Output and a zone's
   output take the last column, a zone's input the first. A big block (a frame or zone of three
   or more columns) gets a column of its own, except a satellite (NF021): a big block with
   nothing linked into it takes the column right before its first consumer, at the top or
   bottom of that column, and reaches to the left over the earlier columns, above or below
   everything there (`columns.py`). A container with satellites is laid out with and without
   them and the cheaper one is kept (decided on fresh layouts, see "Determinism and stability").
6. **Lanes** (`ranking.py`). A link that spans several columns gets one dummy per column it
   crosses, shared by every link from the same output socket (a bus with taps).
7. **Ordering** (`ordering.py`, `force.py`). The order inside each column is found by crossing
   reduction: an initial order from the last column back, then barycenter sweeps down and up
   (weighted towards main inputs), transposition of neighbours, and swaps of commutative inputs,
   counting crossings between socket heights (a block's pairs of ports too, step 4). A second
   order comes from a force-directed
   relaxation: links are springs, items in a column repel each other, heights move until they
   settle, and each column is sorted by height.
8. **Placement** (`placement.py`, `relax.py`). Three ways to find heights for a given order:
   - `blocks`: links are made straight in order of priority (geometry flow, main inputs,
     bundles of parallel links, lanes) by merging the items they join into blocks, as long as no
     column overlaps and the layout does not grow too tall; then the blocks are compacted
     (separation constraints from the column order, solved by pulling each block to the
     weighted median of what its links want and merging blocks that collide), with a weak pull
     towards a common top line;
   - `balanced`: the same without the pull to the top line, and the zone output free to move:
     blocks sit where their links want them;
   - `relax`: spring relaxation (each item moves to the weighted mean of what its links want,
     each column restacked by isotonic regression so nothing overlaps), then nearly straight
     links are straightened by moving groups of items.

   In a zone, each placement runs with each **zone output mode** (`ZONE_OUT`): `level` keeps the
   zone output on the zone input's line (the socket they share, else their tops); `median` and
   `mean` free it: a soft pull to that line (`ZONE_LEVEL`) plus the pull of its links, resolved
   by the weighted median (blocks: the compaction itself; relax: the median of the spring
   targets) or the weighted mean (blocks: the output block is moved to the mean within its
   constraints after compaction; relax: the mean of the spring targets). A free zone output is
   left out of the pull to the top line, may move in the slide pass, and drags the nodes aligned
   with it (the chain before it). The zone frame follows by itself: Blender draws a zone around
   its nodes.
9. **Columns and tracks** (`columns.py`). Column x positions from the widest node, and one
   vertical routing track per source socket in each gap. Tracks are ordered to avoid crossings:
   exactly (dynamic programming over subsets) for up to 8 tracks, else by moves of single
   tracks. Crossings inside a bundle and wires that run into another wire's corner cost more,
   which nests a bundle like stairs. Then tracks one above the other (40 units apart or more)
   share one x, while tracks that overlap in height keep their order (NF036). Where a labelled
   wire turns next to a node, the gap widens
   so its label, centred above the turn, clears the node (NF041). Items with no link at all go
   under the layout where they make it grow least: right below what is above them, within its
   width if they fit (NF021).
10. **Cost and search** (`cost.py`, `search.py`, `engine.py`). Every candidate is laid out in
    full and priced by the layout cost (below). The cheapest candidate is improved by a local
    search; its moves, the ones that change a whole side first: a port of a zone above the zone
    input or back (NF033), a satellite to either end of its column (NF021), a lane, all lanes of
    one node, or everything one node feeds to the top or bottom of their columns or right above
    or below their nodes (NF033), swap commutative inputs, change the placement method, let a
    lane end bend, move a node to the top or bottom, swap two neighbours. The result gets a
    longer search and a final slide pass, which moves a group of nodes held together by straight
    links up or down when that makes one more link straight (and the cost drops). Then the
    layout of the current order is tried (stability, see above). Budgets count layouts, not
    seconds, so the result is deterministic. In a zone, the level and the free zone output modes
    are two groups searched apart (each seed, the final search and the slide), since the orders
    that suit one output height rarely suit the other; both go to the parent (step 4).
11. **Routing** (`routes.py`). The route segments of all containers become one reroute tree per
    source socket: shared points become taps, points where a route goes straight on are
    dropped. A link into a multi-input slot turns at the slot's height, like any other link;
    the track order nests the links of one socket so they do not cross, and the cost does not
    count their last runs (a slot apart) as collinear wires or as reroutes on a wire.
    With NF035, `Model` gives each such slot a fan point instead (`Model._fan`): the layout
    routes the link to it (the node reaches out on its left by the fan's depth, `reach_l`, so
    the tracks of the gap keep clear of the fan), and `Formatter.place` adds the last stretch,
    from the fan point to the slot; the fan point becomes a reroute.
    Then the whole drawing is tidied (`wires.py`): runs that are almost level are made level
    (NF034), and single horizontal runs move to another free height when that removes a
    crossing, a U-jog, a landing or a run along a node edge or zone outline, never onto a node
    (NF031-NF034). Labels go back on the first reroute of their wire (a new reroute near the
    source if the wire has none), never where their text would overlap another label or a node;
    with NF041, on the first reroute where the text is clear of labels, nodes and wires (also the
    greyed copies Blender shows on the later reroutes, `labels.py`), else on a new reroute on the
    run into it.
    If the layout put a node where Blender draws its rows otherwise than measured (across y = 0,
    see "Orthogonal wires"), the tree is laid out again with the offsets of where the nodes go,
    until the offsets hold (at most twice more; layouts that go round in a circle settle on the
    one made with the smallest offsets).
12. **Write back** (`blend.py`). Node locations (on the pixel grid), new reroutes and links are
    written to Blender. New links are made before old reroutes are removed, so no input is left
    unlinked on the way. Links into a multi-input socket are made again in their original order.
    Then `ortho.straighten` makes every drawn segment orthogonal (see "Orthogonal wires"),
    reroutes left in the middle of a straight run are removed, and if straighten nudged the
    Group Output, the whole tree moves back by as much, so the tree stays where it was.
13. **Logic check and revert** (`check.py`, `api.py`). Before formatting, a logic fingerprint of
    the tree is taken: node properties and socket values (hidden ones too), parents, zone pairs,
    the group interface, links resolved through reroutes, and the order of multi-input links.
    Copies of an input node count as the same source, and the two inputs of a commutative pair
    are compared as an unordered pair. Only the tree is compared: settings of a material, world
    or scene outside its node tree are never touched. After formatting, the fingerprint is taken again; on any
    difference (or any error) the tree is restored from a snapshot and the format is reported as
    failed. Formatting repeats until nothing moves (normally two passes).
14. **Checks** (`lint.py`, `metrics.drawing`, `api.check_tree`). The tree as Blender draws it
    becomes the same drawing the tidy pass works on, and each rule has a test on it: curves and
    off segments, wires behind nodes, overlapping reroutes, bundle crossings, U-jogs, landings and
    tiny steps that a free height would remove, runs along node edges and outlines, crossings
    that moving one run would remove, shared points and collinear wires, frames far from their
    consumer, labels. NF010 compares the copy plan, NF011 looks for crossing wires into a
    commutative pair, and NF900 (not formatted) tries a format on a snapshot.

### Snapshots

`Formatter(model, record=True)` keeps plain-data snapshots of the phases in
`formatter.snapshots`: the tree with direct links ('direct'), the orders, seeds, search and
slide of each container ('seed n: order', 'seed n', 'search', 'slide'), and the final drawing
('final'). `tools/animate.py` uses them for the demo animation.

## Orthogonal wires

"Straight" means 100% horizontal or vertical as Blender draws the wire: a segment counts as
orthogonal when its ends differ by at most 0.5 node units in x or in y. The formatter guarantees
this for every drawn segment, at the UI scale it ran at.

Why the UI scale matters: Blender draws a node at its location rounded to whole pixels (location
times the UI scale) and its sockets whole pixels below that; a reroute's dot sits exactly at its
location. At UI scale 1 a pixel is a node unit and everything lines up on whole units. At another
scale (Resolution Scale 1.25, 1.5, ..., or a display set to 150%) the socket offsets, in node
units, are not the scale-1 ones divided evenly: a layout made at scale 1 is a few units off at
1.5, and at
fractional scales Blender rounds the float height of each row of a node towards zero, row after
row from its top, so the rows of a node above y = 0 are a pixel taller than below it: a tall node
is several units taller above 0. No layout is exact at two scales at once, so:

1. The layout is made at the UI scale of the session, which is the scale the user sees in the
   add-on. The command line uses the preferences Blender starts with: run it without
   `--factory-startup` so it uses yours, or give the scale with `--ui-scale`.
2. Node locations go on that scale's pixel grid (`ortho.to_px`). Every node is measured twice,
   drawn below y = 0 and above it (`api.read_tree`), and `model.at` gives its socket offsets for
   where it is drawn (a node across 0 takes, for each stretch between two sockets, the heights
   of the side its middle is on). The measures do not depend on where the nodes are, so each pass
   sees the same tree; the layout uses the offsets of where each node is, and is made again when
   it moves a node across 0 (step 11). Measured anywhere else, a link the layout made straight
   into a low socket of a tall node could be off by more than straighten may nudge, and got a
   step too small to see.
3. After writing, `ortho.straighten` reads back what Blender drew and removes what rounding
   left, until nothing is off: each reroute takes the exact height of the socket its horizontal
   wire runs to (the source first) and reroutes joined by a wire share one height or x; a
   straight link between two nodes that is a little off moves its destination node (else its
   source) onto the line, left to right so a chain lines up in one round, at most 4 units and 3
   times per node; what is still off gets an extra bend (two reroutes). At scale 1 this pass
   mostly places the reroutes of multi-input slots (half units); at 1.5 it also moves a few
   nodes by a pixel or two. With NF035, the stretch of a fan into a multi-input slot is left as
   it is (`ortho.fanned`): it is meant to be diagonal, and its reroute keeps the height of the
   wire that runs into it.
4. `--check` (and the Check Current Tree button) counts every drawn segment that is not orthogonal before
   anything else, so a file formatted at another scale is reported.

A Geometry Nodes group that a modifier uses, directly or nested, is drawn through that object and
the group path from the modifier's tree, as the user sees it: some nodes (Bake) draw more rows
there than in a pinned editor.

## Determinism and stability

- **One deterministic pass.** The search runs one seed: the same input gives the same layout,
  every time. Several seeds (`params.SEEDS`, for experiments) lower the layout cost by about 3%
  on the test trees, a difference hard to see, for about 3 times the time.
- **Idempotent.** Formatting a formatted tree changes nothing (`--check` passes right after
  `--fix`): tested on 106 trees at UI scale 1 and 1.4.
- **The current layout is the tie-breaker.** Besides the fresh layout (which depends on the graph
  only), each container is also laid out in the order its nodes and wires have now (each column
  sorted by height; a lane by where its wire crosses the column), without search. That one is
  kept when it costs no more than the fresh one (`params.STABLE`, 0 by default; None turns it
  off). On a formatted tree the fresh layout is the current one and stays. The copy plan of
  input nodes and the choice of satellite blocks (NF021) depend on the graph only.
- **Stability after a small edit.** Inserting a node usually adds a column, which shifts what is
  before it; the tie-breaker keeps more of the order: over 16 small edits of the test trees, 729
  pairs of nodes changed their left/right or above/below order with it and 835 without (of 5172
  pairs). Two different starting layouts of one graph can therefore format differently when both
  results cost the same.

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
| `W_LABEL` | 6 | each label (or greyed copy, above every turn of a labelled wire) over another label, a node or a wire (NF041) |
| `W_LABEL_BEND` | 1 | extra for each labelled link that is not straight: its turns show the label twice more (NF041) |

The other constants in `params.py` set spacing (gaps between nodes, columns and tracks), the
search budgets (seeds, candidates, layouts per search), the placement methods, the zone output
modes (`ZONE_OUT`, `ZONE_LEVEL`) and `SEED_ONLY` (run a single seed: tests).

## Algorithms and references

- Layered drawing (ranking, ordering, coordinate assignment): K. Sugiyama, S. Tagawa, M. Toda,
  "Methods for visual understanding of hierarchical system structures", IEEE Transactions on
  Systems, Man, and Cybernetics 11(2), 1981.
- Barycenter and median crossing reduction: Sugiyama et al. 1981; P. Eades, N. Wormald, "Edge
  crossings in drawings of bipartite graphs", Algorithmica 11, 1994.
- Transposition of neighbours and long edges as chains of dummies: E. R. Gansner, E. Koutsofios,
  S. C. North, K.-P. Vo, "A technique for drawing directed graphs", IEEE Transactions on
  Software Engineering 19(3), 1993.
- Blocks of aligned links and their compaction, and the balanced variant: U. Brandes, B. Köpf,
  "Fast and simple horizontal coordinate assignment", Graph Drawing 2001. nodefmt aligns by link
  priority instead of medians and compacts with its own constraint solver.
- Compaction with separation constraints (merging colliding blocks): T. Dwyer, K. Marriott,
  P. J. Stuckey, "Fast node overlap removal", Graph Drawing 2005 (VPSC).
- Ports and orthogonal routing between layers: C. D. Schulze, M. Spönemann, R. von Hanxleden,
  "Drawing layered graphs with port constraints", Journal of Visual Languages and Computing 25(2),
  2014 (Eclipse Layout Kernel, ELK Layered).
- Force-directed placement: T. M. J. Fruchterman, E. M. Reingold, "Graph drawing by
  force-directed placement", Software: Practice and Experience 21(11), 1991 (the graph view of
  Obsidian uses d3-force, the same idea).
- Restacking a column with the least weighted displacement: pool adjacent violators for
  isotonic regression, M. Ayer et al., Annals of Mathematical Statistics 26(4), 1955.
- Track order: an instance of linear ordering, solved by dynamic programming over subsets
  (Held-Karp style) for small gaps and by local search otherwise.
- Search: multi-start (seeded) local search over the discrete choices of the layout.

## Files

```
nodefmt/  (the extension)
  __init__.py   add-on entry (register)
  blender_manifest.toml  extension manifest (Blender 4.2+ extensions)
  ui.py         add-on: sidebar panel, buttons, progress, Check results and marks, rule toggles
  rules.py      rule codes and names, nodefmt.toml, --select/--ignore, parameters per rule
  lint.py       checks: the rules a drawn tree breaks, with codes
  wires.py      the drawn wires of a whole tree: faults, tidy pass, zone outlines
  api.py        format a tree with logic check and revert; is_formatted; the trees of a file
  draw.py       make Blender draw a tree (node sizes, socket positions)
  sockets.py    socket positions from Blender's runtime data (ctypes; from Node Arrange)
  ortho.py      UI scale, pixel grid, multi-input slots; read back and straighten drawn wires
  model.py      read a tree as plain data; the Model the layout works on
  dup.py        copies of input-like nodes: plan (pure) and realize (Blender)
  part.py       Sort Selection: a part of the tree with pins for its links, placement, routing
  layout.py     containers, nesting, absolute positions, routes, labels, geometry()
  engine.py     layout of one container: the driver (seeds, search, slide) and finish
  graph.py      items, edges, candidates and shared helpers of the engine
  params.py     all tunable constants and cost weights
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
nodefmt_cli.py  command line (check / fix)
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
examples/       one small tree per rule that breaks it (NF0xx.blend; a second one: NF0xx-<what>.blend)
tests/
  run_tests.py  tests from the examples (check, sort, logic, idempotency, rule off)
  test_operators.py  the add-on operators: progress, Esc, undo, Sort Selection, Check
docs/           usage, rules, configuration, command line, limitations, this page
```
