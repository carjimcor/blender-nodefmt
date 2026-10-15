# Rules

Every behaviour of nodefmt is a rule with a code, as in ruff. Guarantees (NF001-NF005) always
hold. Style rules can be switched off: with their checkbox in the panel (or in Preferences >
Add-ons > nodefmt), with `ignore = ["NF031"]` in [nodefmt.toml](CONFIGURATION.md), or with
`--ignore NF031` on the [command line](CLI.md). A rule that is off is neither applied when
sorting nor reported by a check. NF022, NF023 and NF035 are off by default: select them by
code, by name or with `"ALL"`.

| Code | Name | Kind | What it does |
|---|---|---|---|
| [NF001](#nf001-no-curved-links) | no-curved-links | guarantee | A link that is not straight turns on reroutes. |
| [NF002](#nf002-no-links-behind-nodes) | no-links-behind-nodes | guarantee | No wire passes behind a node. |
| [NF003](#nf003-orthogonal-segments) | orthogonal-segments | guarantee | Every segment is horizontal or vertical (within half a unit) at the UI scale used. |
| [NF004](#nf004-no-overlapping-reroutes) | no-overlapping-reroutes | guarantee | No two reroutes of different wires closer than 10 units. |
| [NF005](#nf005-logic-unchanged) | logic-unchanged | guarantee | A sort that would change the logic is undone. |
| [NF010](#nf010-duplicate-input-nodes) | duplicate-input-nodes | style | Input-like nodes get a copy next to each distant group of consumers. |
| [NF011](#nf011-commutative-swaps) | commutative-swaps | style | The two inputs of a commutative node may be swapped to remove a crossing. |
| [NF020](#nf020-free-zone-outputs) | free-zone-outputs | style | A zone's output may sit where its inputs are instead of level with the zone input. |
| [NF021](#nf021-blocks-next-to-consumer) | blocks-next-to-consumer | style | A frame or zone with nothing linked into it sits right before the node it feeds; one with nothing linked at all sits compactly under the tree. |
| [NF022](#nf022-converging-shape) | converging-shape | style, off by default | A tree that converges on one output may take a ">" shape. |
| [NF023](#nf023-stacked-fields) | stacked-fields | style, off by default | A short chain of field nodes is stacked above or below the node it feeds, in its column. |
| [NF030](#nf030-staircase-bundles) | staircase-bundles | style | Wires leaving or entering one node are nested like stairs and do not cross. |
| [NF031](#nf031-no-u-jogs) | no-u-jogs | style | No U-jogs, landings or tiny steps that a free height would remove. |
| [NF032](#nf032-wire-clearance) | wire-clearance | style | Wires keep clear of node edges, frame borders and zone outlines. |
| [NF033](#nf033-avoid-crossings) | avoid-crossings | style | A crossing that can be avoided is avoided. |
| [NF034](#nf034-no-junction-look) | no-junction-look | style | Wires never share a point or run on one line. |
| [NF035](#nf035-fanned-multi-inputs) | fanned-multi-inputs | style, off by default | The links into a Join Geometry or Join Strings arrive spread out and converge in a short fan. |
| [NF036](#nf036-shared-tracks) | shared-tracks | style | Vertical runs one above the other in a gap share one x. |
| [NF040](#nf040-label-first-reroute) | label-first-reroute | style | A reroute label goes on the first reroute of its wire. |
| [NF041](#nf041-label-clearance) | label-clearance | style | Reroute labels, and the greyed copies Blender shows, overlap no label, node or wire. |

Check also reports **NF900 not-formatted** when a sort would move anything.

## The examples

Every rule has a small synthetic tree in `examples/NF0xx.blend` (one Geometry Nodes group,
"NF0xx" plus the rule name; open the file, switch an editor to Geometry Node Editor and pick the
group), and a before and after image made from it. Some rules have a second example,
`examples/NF0xx-<what>.blend`, shown and tested the same way:

- **Guarantees**: before, the example as built, which breaks the rule; after, the example sorted
  with no style rules at all.
- **Style rules**: before, the example sorted with every style rule off (the file is saved that
  way), so the rule is broken the way the formatter leaves it without the rule; after, the
  example sorted with only that rule on. The two differ only by what the rule does.

The images are Blender screenshots at UI scale 1.0 (NF034 at 1.25, see there). Each place that
breaks the rule is ringed in red in the before image, where the check gives a place (NF010,
NF020 and NF022 have none). `tests/run_tests.py` checks every example (see
[CONTRIBUTING.md](../CONTRIBUTING.md)); `tools/make_examples.py` rebuilds them and
`tools/capture_examples.py` the images.

## Guarantees

### NF001 no-curved-links

Guarantee. A link that is not straight turns on reroutes: no link is drawn as a curve or a
diagonal.

Why: a curve between two columns crosses other wires at odd angles and hides where it goes;
straight runs and right angles read like a circuit diagram.

Example: Set Position sits lower than the nodes it connects, so both links curve. After the sort
it is level with them and both links are straight.

With NF035 (off by default), the last stretch of each link into a multi-input socket, from its
fan point to its slot, is drawn diagonal (or curved, with Blender's noodle curving): that is the
fan, not a fault of NF001 or NF003.

Images: before, the example as built; after, sorted with no style rules.

| Before | After |
|---|---|
| ![NF001 before: two curved links](rules/NF001-before.png) | ![NF001 after: straight links](rules/NF001-after.png) |

### NF002 no-links-behind-nodes

Guarantee. No wire passes behind a node.

Why: a wire behind a node looks as if it were connected to it, and its own path is hidden.

Example: the Value wire runs straight through Transform Geometry. After the sort it goes over
Transform Geometry. It crosses the Geometry wire twice on the way: avoiding that is NF033, off
here.

Images: before, the example as built; after, sorted with no style rules.

| Before | After |
|---|---|
| ![NF002 before: a wire behind Transform Geometry](rules/NF002-before.png) | ![NF002 after: the wire goes over the node](rules/NF002-after.png) |

### NF003 orthogonal-segments

Guarantee. Every drawn wire segment is exactly horizontal or vertical (within half a unit) at
the UI scale the tree is sorted for.

Why: a segment one or two units off is drawn as a slightly slanted, jagged line. Blender rounds
node positions and socket offsets to pixels, so this happens easily at a fractional UI scale;
the sort reads back what Blender draws and straightens what rounding left (see
[How it works](ALGORITHM.md#orthogonal-wires)).

Example: a reroute 1.5 units above the line of its wire. After the sort the link is straight.

Images: before, the example as built; after, sorted with no style rules.

| Before | After |
|---|---|
| ![NF003 before: a reroute slightly off the line](rules/NF003-before.png) | ![NF003 after: a straight link](rules/NF003-after.png) |

Second example (`NF003-rows`, at UI scale 1.4): Blender rounds the float height of each row of a
node towards zero, so the rows of a node above y = 0 are a pixel taller than below it. The sort
measures every node below 0 and puts the whole tree below 0, so the measures hold; measured
below 0 but drawn above it, the Scale input of this tall Instance on Points was 4 units lower
than measured: the wire from Multiply got a step too small to see, two reroutes on
one spot that look like a slanted stub. After the sort the wire is straight. The test also checks
that no wire is left with such a step.

| Before | After |
|---|---|
| ![NF003-rows before: the Points wire off its line](rules/NF003-rows-before.png) | ![NF003-rows after: straight wires into the tall node](rules/NF003-rows-after.png) |

### NF004 no-overlapping-reroutes

Guarantee. No two reroutes of different wires sit on top of each other (closer than 10 units).

Why: two reroutes on one spot look like one, as if the wires were joined.

Example: two crossing wires turn 4 units apart. After the sort each wire turns at its own place.
The wires still cross: Combine XYZ cannot swap its inputs, and copying the Group Input is NF010,
off here.

Images: before, the example as built; after, sorted with no style rules.

| Before | After |
|---|---|
| ![NF004 before: reroutes of two wires on one spot](rules/NF004-before.png) | ![NF004 after: the reroutes apart](rules/NF004-after.png) |

### NF005 logic-unchanged

Guarantee. Sorting never changes what the tree computes. Before a sort nodefmt takes a logic
fingerprint of the tree: node types, properties and socket values (hidden ones too), parents,
zone pairs, the group interface, and every link resolved through reroutes, with the order of
multi-input links. Copies of input-like nodes count as one source and the two inputs of a
commutative node as a pair. After the sort the fingerprint is taken again; if anything differs
the tree is restored and the sort reports an error.

Example: a messy tree, with nodes out of order and links that curve and cross. After the sort
the layout is new, and the logic fingerprint is the same: each image shows the first 12 hex
digits of a hash of the fingerprint of its tree, under the tree.

Images: before, the example as built; after, sorted with no style rules.

| Before | After |
|---|---|
| ![NF005 before: a messy tree and its logic fingerprint](rules/NF005-before.png) | ![NF005 after: the sorted tree with the same fingerprint](rules/NF005-after.png) |

## Style rules

### NF010 duplicate-input-nodes

Style. Input-like nodes (Group Input, Named Attribute, Position, constants, ...) get a copy next
to each distant group of consumers instead of long wires from one node. Never copied: String
nodes, labelled nodes, and nodes that load data (Image Texture, Render Layers, ...).

Why: a long wire across the tree is hard to follow and crosses everything on its way; a copy
next to the consumer says the same thing locally.

Example: the Scale input of the Group Input runs under the whole tree to Transform Geometry.
With the rule, Transform Geometry gets its own Group Input.

Off: the tree keeps one Group Input and the long wire.

Images: before, sorted with every style rule off; after, sorted with only NF010.

| Before | After |
|---|---|
| ![NF010 before: a long wire from the Group Input](rules/NF010-before.png) | ![NF010 after: a Group Input copy next to Transform](rules/NF010-after.png) |

### NF011 commutative-swaps

Style. The two inputs of a commutative node (Add, Multiply, Minimum, Maximum, AND, OR, XOR,
Equal, Not Equal, Add Shader) may be swapped when that removes a crossing.

Why: a + b is b + a, so the crossing is free to remove.

Example: X goes to the lower input of Add and Y to the upper one, so the wires cross; Separate
XYZ cannot change the order of its outputs. With the rule the inputs are swapped and the wires
are straight.

Off: the links keep their inputs and the crossing stays.

Images: before, sorted with every style rule off; after, sorted with only NF011.

| Before | After |
|---|---|
| ![NF011 before: crossing wires into Add](rules/NF011-before.png) | ![NF011 after: swapped inputs, no crossing](rules/NF011-after.png) |

A frame or zone is laid out before what is around it, so it cannot see where the wires that
enter it come from. When swapping the inputs of a node inside it only exchanges two of its
ports (the node is in its first column, or each input comes straight from a port that feeds
nothing else), the swap is left to the level around the block, which sees both wires; it is
laid out with the inputs as the block left them and with them free, and keeps the cheaper.

Second example (`NF011-frame`): Zeta and Alpha come in the order of the Group Input's sockets
and feed the Add in frame "Sum", Alpha the upper input; the wires cross at the frame's left
side. With the rule the Add's inputs are swapped and nothing crosses.

| Before | After |
|---|---|
| ![NF011-frame before: crossing wires into a frame](rules/NF011-frame-before.png) | ![NF011-frame after: no crossing](rules/NF011-frame-after.png) |

Third example (`NF011-zone`): the same in a frame inside a Repeat zone, where the Add gets the
doubled iteration from inside the zone and Alpha from outside it. A node whose two inputs both
come from outside a zone is laid out outside the zone, and one with one input from outside is
swapped by the zone itself, which sees both wires.

| Before | After |
|---|---|
| ![NF011-zone before: crossing wires into a frame in a zone](rules/NF011-zone-before.png) | ![NF011-zone after: no crossing](rules/NF011-zone-after.png) |

### NF020 free-zone-outputs

Style. A zone's output may sit where its inputs are instead of level with the zone input.

Why: the wires into the zone output can then be straight, at the price of a zone that is not
rectangular.

Example: with the Repeat output level with the Repeat input, Instance on Points sits lower and
the wire into its Points input steps down. With the rule the zone output is 25 units higher,
Instance on Points rises with it, and the wires from the Repeat input and into the Repeat output
are straight.

Off: the zone output stays level with the zone input (its item sockets on one line).

This rule has no geometric check of its own: Check reports such a tree as not formatted (NF900).

Images: before, sorted with every style rule off; after, sorted with only NF020.

| Before | After |
|---|---|
| ![NF020 before: a level zone output and a bent wire](rules/NF020-before.png) | ![NF020 after: the zone output moved up, the wires straight](rules/NF020-after.png) |

### NF021 blocks-next-to-consumer

Style. A frame or zone with nothing linked into it sits in the column right before the node it
feeds, above or below the main flow, instead of at the far left.

Why: a self-contained block (a frame that builds an instance, a constant) belongs to where it is
used; at the far left it needs a wire across the whole tree.

Example: the "Cube" frame feeds Instance on Points at the end of the tree. Without the rule it
takes the first columns, far from its consumer; with it, it sits right before Instance on
Points, below the main row.

Off: the frame takes the first columns, far from its consumer.

Images: before, sorted with every style rule off; after, sorted with only NF021.

| Before | After |
|---|---|
| ![NF021 before: a frame far from its consumer](rules/NF021-before.png) | ![NF021 after: the frame next to its consumer](rules/NF021-after.png) |

A frame or zone with nothing linked at all (notes, a test, a block nothing uses yet) sits under
the tree where it makes the tree grow least: right below what is above it, within the tree's
width if it fits, beside a satellite rather than under it. Check reports such a frame that could
sit more than 100 units higher in the free space under the tree.

Second example (`NF021-alone`): frame "Cube" feeds Instance on Points late in a long row, and
frame "Test" is linked to nothing. Without the rule "Test" is put under the left end of the tree;
with it, "Cube" sits under the end of the row and "Test" beside it, in the space under the start
of the row.

Off: blocks with nothing linked go in a row under the tree, from its left edge.

| Before | After |
|---|---|
| ![NF021-alone before: a frame with nothing linked under the left end](rules/NF021-alone-before.png) | ![NF021-alone after: the frame beside the satellite](rules/NF021-alone-after.png) |

### NF022 converging-shape

Style, off by default. A tree that converges on one output may take a ">" shape, with the
output in the middle of its inputs, instead of everything hanging from a common top line. Off by
default because on the test trees it leaves more crossings than the layouts without it.

The sort tries this placement next to the others and keeps it only when it costs less (fewer
bends, shorter wires). It only differs from the usual placement where a block is not held by a
straight link: in a plain tree of Math nodes every block is, and the result is the same with the
rule on and off. It pays off in trees where branches of different lengths share inputs.

Example: a short branch (one Subtract) and a long one (three Subtracts) converge on a Divide;
both use the two group inputs. Without the rule, Divide and the output hang from the top line
and the long branch climbs up to them like a staircase. With it, Divide sits between its two
inputs, and the tree is lower.

Off: the ">" placement is not tried.

This rule has no geometric check of its own: Check reports such a tree as not formatted (NF900).

Images: before, sorted with every style rule off; after, sorted with only NF022.

| Before | After |
|---|---|
| ![NF022 before: the tree hangs from the top line](rules/NF022-before.png) | ![NF022 after: Divide between its inputs](rules/NF022-after.png) |

### NF023 stacked-fields

Style, off by default. A short chain of field nodes that feeds one input of a node and nothing
else sits in that node's column, stacked right above or below it, instead of in the columns
before it.

Why: small field chains (Index -> Compare into a Selection, Position into a Sample Index) are
read as part of the node they feed. In columns of their own they push the tree apart, and a
chain that ends inside a zone gets wires across the whole zone.

A chain is up to three nodes linked one after the other: the first has nothing linked in, each
has a single link out, the last links into one input of the consumer, and none has a geometry
socket or is a zone, output, reroute or Group Input node. All of them are in the consumer's
frame. With one chain, it goes above the consumer when that crosses fewer of the consumer's
other linked inputs, and on a tie when its input is in the upper half of the node. With several,
the chain into the highest input goes above and the one into the lowest goes below; the others
are not stacked. Each wire of a stack leaves its node to the right, turns in the gap between the
two nodes and enters its socket from the left. The nodes stand at the left edge of the column
like the others, and the gaps beside the column widen for the wires round the side.

Example: Index -> Equal feeds the Selection of Store Named Attribute, and Position -> Length its
Value. Without the rule both chains take the columns before Store Named Attribute. With it,
Index and Equal sit above it and Length and Position below it.

Off: chains are laid out like any other node.

This rule has no geometric check of its own: Check reports such a tree as not formatted (NF900).

Images: before, sorted with every style rule off; after, sorted with only NF023.

| Before | After |
|---|---|
| ![NF023 before: the chains in the columns before their consumer](rules/NF023-before.png) | ![NF023 after: the chains stacked above and below their consumer](rules/NF023-after.png) |

### NF030 staircase-bundles

Style. Wires that leave one node or enter one node are nested like stairs and never cross each
other.

Why: wires of one node that cross each other are the hardest to follow, since they start or
end side by side.

Example: Combine XYZ and Separate XYZ both feed the Group Output, Combine XYZ the upper socket.
Without the rule Combine XYZ sits lower, so the wire from Separate XYZ comes down across the
wire of Combine XYZ just before the Group Output. With the rule Combine XYZ sits on top and the
two wires do not cross.

Off: crossings inside a bundle cost as much as any other crossing.

Images: before, sorted with every style rule off; after, sorted with only NF030.

| Before | After |
|---|---|
| ![NF030 before: crossing wires into the Group Output](rules/NF030-before.png) | ![NF030 after: nested wires](rules/NF030-after.png) |

### NF031 no-u-jogs

Style. A route does not reverse its vertical direction unless a node is in the way, has no
landing that could merge with the level before or after it, and no step so small that its two
reroutes sit on one spot.

Why: a wire that climbs over nothing and comes back down looks like it avoids something that is
not there.

Example: without the rule the Height wire climbs over Separate XYZ and comes all the way back
down to Combine XYZ. With it, the wire goes down at once and runs below the other wires.

Off: the final pass over the drawing no longer moves runs to remove U-jogs and landings.

Images: before, sorted with every style rule off; after, sorted with only NF031.

| Before | After |
|---|---|
| ![NF031 before: a U-jog](rules/NF031-before.png) | ![NF031 after: no U-jog](rules/NF031-after.png) |

### NF032 wire-clearance

Style. Wires keep clear of node edges, frame borders and zone outlines (no wire runs along
them).

Why: a wire along an edge merges with it and looks like part of the node or the frame.

Example: the Offset wire enters a Repeat zone to the Add inside it. Without the rule it runs
along the bottom of the zone's outline; with it, the lane keeps clear of the outline.

Off: lanes in a zone keep the usual gap from the nodes (20 units instead of 34), and runs along
edges and outlines cost nothing.

Images: before, sorted with every style rule off; after, sorted with only NF032.

| Before | After |
|---|---|
| ![NF032 before: a wire along the zone outline](rules/NF032-before.png) | ![NF032 after: the wire clear of the outline](rules/NF032-after.png) |

### NF033 avoid-crossings

Style. A crossing that can be avoided (a lane on the other side, a wire entering a zone above its
input) is avoided.

Why: every crossing is a place where the eye can take the wrong wire.

Example: without the rule the Value wire goes over Transform Geometry and crosses the Geometry
wire twice. With it, the wire runs under Transform Geometry and crosses nothing.

Off: a crossing costs little more than a bend and lanes keep to one side.

Images: before, sorted with every style rule off; after, sorted with only NF033.

| Before | After |
|---|---|
| ![NF033 before: an avoidable crossing](rules/NF033-before.png) | ![NF033 after: no crossing](rules/NF033-after.png) |

### NF034 no-junction-look

Style. Different wires never share a point or run on one line, and no reroute sits in the middle
of a straight run: nothing looks like a junction.

Why: a dot on a straight wire, or two wires on one line, read as a junction where wires meet.

Example: at UI scale 1.25, rounding to the pixel grid leaves a reroute in the middle of the
straight Z wire into Subtract, just before it crosses the Vector wire: a dot on a straight wire
looks like a junction. With the rule the run is made level and the reroute is gone. The images
are at UI scale 1.25 (the example stores it): at 1.0 nothing is rounded and this does not
happen in a tree this small.

Off: almost level runs are not made level, reroutes left in straight runs stay, and wires on
one line or reroutes on another wire cost nothing.

Images: before, sorted with every style rule off; after, sorted with only NF034 (both at UI
scale 1.25).

| Before | After |
|---|---|
| ![NF034 before: a reroute in a straight wire](rules/NF034-before.png) | ![NF034 after: no reroute](rules/NF034-after.png) |

### NF035 fanned-multi-inputs

Style, off by default. The links into a multi-input socket (Join Geometry, Join Strings, Mesh
Boolean, ...) arrive a widget unit (20 units) apart and converge only in a short fan right
before the socket, instead of running a quarter widget unit (5 units) apart all the way from the
gap before the node.

Why: the order of the links into a Join Geometry or Join Strings matters, and five units apart
their wires blur into one thick band: it is hard to see which wire goes to which slot. Spread
out, each wire can be followed to its slot.

Each link runs to its fan point, a reroute a little left of the socket, and from there straight
to its slot. The fan points are centred on the socket and keep 10 units from the wires into the
node's other inputs (the Delimiter of a Join Strings): the fan moves away from them and, only if
that is not enough, spreads less, never less than 10 units. A slot whose fan point is level with
it (the middle one of an odd number) needs no fan. The fan reaches 30 units to the left of the
socket, more for a big fan (at least 1.5 times its largest drop), and the gap before the node
widens so the vertical runs of the wires stay clear of it. The last stretch of each wire is
diagonal; with Blender's noodle curving it is drawn as a small curve, and with a curving of 0
as a straight diagonal. A collapsed node has no fan (all its links meet at the socket).

Example: three Grids feed one Join Geometry. Without the rule their wires turn into the socket
5 units apart. With it they arrive 20 units apart and converge in the last 30 units. The second
example (`NF035-strings`) is a Join Strings whose Delimiter is linked too: the fan of its three
Strings moves down, clear of the Delimiter wire.

Off: the links run to their slots, 5 units apart.

Check reports a multi-input socket whose links arrive less than 10 units apart.

Images: before, sorted with every style rule off; after, sorted with only NF035.

| Before | After |
|---|---|
| ![NF035 before: three wires packed into a Join Geometry](rules/NF035-before.png) | ![NF035 after: the wires spread out and converge in a fan](rules/NF035-after.png) |

| Before | After |
|---|---|
| ![NF035-strings before: the Strings wires packed under the Delimiter](rules/NF035-strings-before.png) | ![NF035-strings after: the fan below the Delimiter wire](rules/NF035-strings-after.png) |

### NF036 shared-tracks

Style. Vertical runs in one gap between columns that lie one above the other share one x,
instead of each taking a track of its own.

Why: wires that turn in the same gap at different heights do not meet, but on tracks of their
own they form a staircase that looks busier than it is and makes the gap wider. On one line they
read as a few clean turns.

The tracks of a gap are first ordered to avoid crossings, as before. Then each track takes the
leftmost x right of every earlier track whose height range comes within 40 units of its own:
tracks that overlap in height keep their order, so no crossing changes, and tracks one above
the other share an x. The gap is as wide as the tracks it still needs.

Example: three Combine XYZ, each fed Y by a Math node a little lower. Without the rule the three
Y wires turn on three tracks, a staircase. With it they turn on one line and the gap is
narrower.

Off: every track of a gap has its own x.

This rule has no geometric check of its own: Check reports such a tree as not formatted (NF900).

Images: before, sorted with every style rule off; after, sorted with only NF036.

| Before | After |
|---|---|
| ![NF036 before: three wires turning on a staircase of tracks](rules/NF036-before.png) | ![NF036 after: the three wires turning on one line](rules/NF036-after.png) |

### NF040 label-first-reroute

Style. The label of a labelled reroute goes on the first reroute of its wire, near the source.

Why: Blender 5 shows a reroute's label, greyed, on every reroute after it on the same wire, so
one label at the start names the whole wire.

Example: without the rule the label "Offset" stays on the reroute nearest to where it was, the
second reroute of the Value wire. With it, the label is on the first.

Off: the label goes on the reroute nearest to where it was.

Images: before, sorted with every style rule off; after, sorted with only NF040.

| Before | After |
|---|---|
| ![NF040 before: a label on the second reroute](rules/NF040-before.png) | ![NF040 after: the label on the first reroute](rules/NF040-after.png) |

### NF041 label-clearance

Style. A reroute label overlaps no other label, no node and no wire, and neither do the greyed
copies of it that Blender shows on the later reroutes of its wire (the reroute auto labels of
Blender 5): a label is drawn once per reroute of its wire, centred above each dot.

Why: a label covered by a node or another label, or labels stacked on top of each other near
the sockets of a node, cannot be read.

The sort measures each label's text as Blender draws it. A labelled wire turns where its labels
clear the nodes beside it (the gap between the columns widens for them), its bends cost a little
more, and overlaps of its labels cost like a crossing near a bend. The label goes on the first
reroute where its text is clear, or on a new reroute on the run into it, where it does not
overlap the greyed copies after it (with this rule, NF040 accepts that). A wire that turns
upwards at a reroute runs through the greyed copy there; that is not counted, since Blender
draws the copy on every reroute.

Example: the Offset wire carries the label "Offset along the normal" and turns right before Set
Position, in a narrow gap: the label and its greyed copy on the second turn cover the nodes on
both sides. With the rule the gap widens and both are clear of the nodes and the other wire.

Off: gaps do not widen for labels, overlaps of labels cost nothing, and a label goes on the first
reroute whose text overlaps no other label.

Images: before, sorted with every style rule off; after, sorted with only NF041.

| Before | After |
|---|---|
| ![NF041 before: a label over the nodes beside it](rules/NF041-before.png) | ![NF041 after: the label clear of nodes and wires](rules/NF041-after.png) |
